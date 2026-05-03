# Color-Matching Balls game module
#
# In-RAM game mode that overlays the LED strip without touching the persisted
# settings.json mode. The main loop calls Game.tick() each iteration when
# is_active() is True; cross-thread mutators (start/stop/shoot) are called
# from the web server on core 1 and queue work for core 0 via a small lock.

import json
import time
import random
import _thread

from config import NUM_LEDS, LED_START_OFFSET, LED_BRIGHTNESS_MAX


# ---------- Gameplay tunables ----------

# Playfield geometry
HOME_SKIP_LEDS = 3          # LEDs at home end excluded from playfield
END_SKIP_LEDS = 0           # LEDs at far end excluded from playfield

# Barrier (white "shield" near home end — protects player; touch = game over)
BARRIER_FRACTION = 0.05    # position from home (fraction of playfield)
BARRIER_BRIGHTNESS = 0.20   # white intensity 0..1

# Enemy shield (far end — hit it with any ball to win the level).
# Always rendered during play; "shootable" once the snake's head has reached
# (or retreated past) the shield position.
ENEMY_SHIELD_FRACTION = 0.7              # base position at level 1 (fraction of playfield)
ENEMY_SHIELD_FRACTION_PER_LEVEL = 0.05   # shifted further toward the enemy each level
ENEMY_SHIELD_FRACTION_MAX = 0.9          # cap so the shield never reaches the far end
ENEMY_SHIELD_BRIGHTNESS = 0.30           # cyan intensity 0..1

# Snake start length per level
START_FRACTION = 0.50       # level-1 start length / playfield
GROW_PER_LEVEL = 2          # extra LEDs per level
MAX_FRACTION = 0.75         # cap on snake start length

# Snake advance rate
GROW_TICK_MS = 3000          # at level 1
GROW_SPEEDUP_MS = 100         # shaved per additional level
GROW_TICK_MIN_MS = 300       # floor

# Ball travel
BALL_TICK_MS = 60
BALL_DEBOUNCE_MS = BALL_TICK_MS
BALL_BECOMES_HEAD_LEVEL = 5  # at this level and up, wrong-color ball joins snake
PENDING_SHOTS_CAP = 8

# Intro timing
INTRO_FLASH_ON_MS = 150
INTRO_FLASH_OFF_MS = 150
INTRO_HS_HOLD_MS = 800
INTRO_MATERIALIZE_MS = 40

# Win/gameover
WIN_ANIM_STEP_MS = 25
WIN_FADE_MS = 600
GAMEOVER_MARCH_SPEEDUP = 4  # march-home runs this much faster than the level's grow cadence

# Persistence
HIGHSCORE_FILE = "/game.json"

# ---------- Colors ----------

COLOR_R = (LED_BRIGHTNESS_MAX, 0, 0)
COLOR_G = (0, LED_BRIGHTNESS_MAX, 0)
COLOR_B = (0, 0, LED_BRIGHTNESS_MAX)
# Secondary colors (mixes). Snake balls only for now; player mix-shooting is wishlist.
COLOR_C = (0, LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX)         # G+B
COLOR_Y = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, 0)         # R+G
COLOR_M = (LED_BRIGHTNESS_MAX, 0, LED_BRIGHTNESS_MAX)         # R+B
COLOR_BARRIER = (
    int(LED_BRIGHTNESS_MAX * BARRIER_BRIGHTNESS),
    int(LED_BRIGHTNESS_MAX * BARRIER_BRIGHTNESS),
    int(LED_BRIGHTNESS_MAX * BARRIER_BRIGHTNESS),
)
COLOR_BLACK = (0, 0, 0)
COLOR_HIGHSCORE = (0, int(LED_BRIGHTNESS_MAX * 0.5), 0)
COLOR_WHITE = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX)
COLOR_ENEMY_SHIELD = (
    0,
    int(LED_BRIGHTNESS_MAX * ENEMY_SHIELD_BRIGHTNESS),
    int(LED_BRIGHTNESS_MAX * ENEMY_SHIELD_BRIGHTNESS),
)

_COLOR_MAP = {
    "R": COLOR_R, "G": COLOR_G, "B": COLOR_B,
    "C": COLOR_C, "Y": COLOR_Y, "M": COLOR_M,
}
_COLORS = ("R", "G", "B")

# Snake palette per level: cyan unlocks at level 3, yellow at 4, magenta at 5+.
def _palette_for_level(level):
    pal = ["R", "G", "B"]
    if level >= 3:
        pal.append("C")
    if level >= 4:
        pal.append("Y")
    if level >= 5:
        pal.append("M")
    return pal


def _load_highscore():
    try:
        with open(HIGHSCORE_FILE, "r") as f:
            return int(json.load(f).get("highscore", 0))
    except (OSError, ValueError):
        return 0


def _save_highscore(score):
    try:
        with open(HIGHSCORE_FILE, "w") as f:
            json.dump({"highscore": int(score)}, f)
    except OSError as e:
        print("game: highscore save failed:", e)


def _scale(rgb, factor):
    if factor <= 0:
        return COLOR_BLACK
    if factor >= 1.0:
        return rgb
    return (
        int(rgb[0] * factor),
        int(rgb[1] * factor),
        int(rgb[2] * factor),
    )


class Game:
    def __init__(self, led, storage):
        """led: LEDController, storage: Storage (unused for now, reserved)."""
        self.led = led
        self.storage = storage

        # Cross-thread coordination
        self._lock = _thread.allocate_lock()
        self._pending_shots = []
        self._pending_start = False
        self._pending_start_level = 1
        self._pending_stop = False

        # Public callback (set by main): on_active_change(active: bool)
        self.on_active_change = None

        # Highscore (in-memory cache; loaded from /game.json)
        self.highscore = _load_highscore()

        # State
        self.state = "inactive"
        self.level = 0
        # Total balls launched in the current game (resets on _begin_game).
        # Used to lock out level adjustments after the player has committed.
        self._game_shots_fired = 0
        # Pending level-restart request (cross-thread): None or target level int.
        self._pending_level_restart = None

        # Playfield bounds (cached on each game start)
        self._pf_start = LED_START_OFFSET + HOME_SKIP_LEDS
        self._pf_end = NUM_LEDS - 1 - END_SKIP_LEDS
        self._pf_len = max(0, self._pf_end - self._pf_start + 1)
        self._barrier_pf_idx = int(self._pf_len * BARRIER_FRACTION)
        # Shield position depends on level; primed in _begin_game.
        self._enemy_shield_pf_idx = int(self._pf_len * ENEMY_SHIELD_FRACTION)

        # Snake state
        # snake_balls[0] is the head (closest to home).
        # head_pf_idx is the playfield index of the head ball.
        self.snake_balls = []
        self.head_pf_idx = 0

        # In-flight balls: list of dicts {"color": "R"|"G"|"B", "pf_idx": int, "last_step_ms": int}
        self.balls = []
        self._last_shot_ms = 0

        # Snake grow timer
        self._next_grow_ms = 0

        # Intro state
        self._intro_flashes_remaining = 0
        self._intro_flash_on = False
        self._intro_flash_next_toggle = 0
        self._intro_hs_until = 0
        self._intro_mat_next_ms = 0
        self._intro_mat_built = 0  # how many balls materialized so far

        # Win-anim state
        self._win_sweep_idx = 0
        self._win_next_step_ms = 0
        self._win_fade_started = False
        self._win_fade_start_ms = 0

        # Gameover state
        self._go_flashes_remaining = 0
        self._go_flash_on = False
        self._go_next_toggle_ms = 0

    # ---------- Cross-thread API ----------

    def is_active(self):
        return self.state != "inactive"

    def start(self, level=1):
        try:
            level = int(level)
        except (TypeError, ValueError):
            level = 1
        if level < 1:
            level = 1
        with self._lock:
            self._pending_start = True
            self._pending_start_level = level

    def stop(self):
        with self._lock:
            self._pending_stop = True

    def shoot(self, color):
        # Accepts any of the 6 colors (R/G/B primaries + Y/C/M mixes).
        # Allowed during intro states too — there it's consumed as a
        # "skip the flashes" signal in _drain_pending_inputs rather than
        # firing a ball.
        if color not in _COLOR_MAP:
            return
        with self._lock:
            if self.state not in ("playing", "intro_flash", "intro_highscore"):
                return
            if len(self._pending_shots) >= PENDING_SHOTS_CAP:
                return
            self._pending_shots.append(color)

    def upgrade_last_ball(self, mix_color):
        """Legacy API kept for backward compatibility. Now equivalent to
        shoot(mix_color) — the upgrade dance is gone (direct mix buttons)."""
        self.shoot(mix_color)

    def shots_fired_this_game(self):
        """Number of balls launched since this game started. Used to lock
        out level adjustments after the player has committed to a level."""
        return self._game_shots_fired

    def restart_at_level(self, level):
        """Restart the running game at a new level. No-op if any ball has
        already been fired this game (anti-cheat for highscore)."""
        try:
            level = int(level)
        except (TypeError, ValueError):
            return
        if level < 1:
            level = 1
        with self._lock:
            if not self._is_active_unlocked():
                return
            if self._game_shots_fired > 0:
                return
            self._pending_level_restart = level

    def _is_active_unlocked(self):
        # state read is atomic; safe without holding the lock for read-only,
        # but we're already inside the lock when called from public methods.
        return self.state != "inactive"

    # ---------- Core-0 tick ----------

    def tick(self):
        now = time.ticks_ms()
        # Drain inputs even when inactive — start request must transition state.
        self._drain_pending_inputs(now)

        if self.state == "inactive":
            return

        self._advance_state(now)
        self._render()

    # ---------- Internals ----------

    def _set_state(self, new_state):
        was_active = self.state != "inactive"
        self.state = new_state
        is_active = new_state != "inactive"
        if was_active != is_active and self.on_active_change is not None:
            try:
                self.on_active_change(is_active)
            except Exception as e:
                print("game: on_active_change error:", e)

    def _drain_pending_inputs(self, now):
        with self._lock:
            do_start = self._pending_start
            do_stop = self._pending_stop
            start_level = self._pending_start_level
            shots = self._pending_shots
            level_restart = self._pending_level_restart
            self._pending_start = False
            self._pending_start_level = 1
            self._pending_stop = False
            self._pending_shots = []
            self._pending_level_restart = None

        if do_stop:
            self._enter_inactive(save=False)
            return

        if do_start and self.state == "inactive":
            self._begin_game(now, start_level)

        if (level_restart is not None
                and self.state != "inactive"
                and self._game_shots_fired == 0):
            # Re-run the intro at the new level. _begin_game also resets the
            # shots counter (which is already 0).
            self._begin_game(now, level_restart)

        # If shots arrive during the flashing intro phases, treat the press as
        # a "skip the flashes" signal — discard the shots and jump straight
        # to materialize, as if both flash sequences and the highscore hold
        # had completed naturally.
        if shots and self.state in ("intro_flash", "intro_highscore"):
            self._enter_intro_materialize(now)
            shots = []  # consumed as skip-input, not as a fired shot

        if shots and self.state == "playing":
            for c in shots:
                self._launch_ball(c, now)

    def _begin_game(self, now, level=1):
        self.level = max(1, int(level))
        self._game_shots_fired = 0
        # Refresh playfield bounds (in case constants change at runtime — defensive)
        self._pf_start = LED_START_OFFSET + HOME_SKIP_LEDS
        self._pf_end = NUM_LEDS - 1 - END_SKIP_LEDS
        self._pf_len = max(0, self._pf_end - self._pf_start + 1)
        self._barrier_pf_idx = int(self._pf_len * BARRIER_FRACTION)
        self._recompute_shield_idx()
        self._enter_intro_flash(now)

    def _recompute_shield_idx(self):
        """Shield position scales with level: base + per-level shift, capped."""
        frac = ENEMY_SHIELD_FRACTION + ENEMY_SHIELD_FRACTION_PER_LEVEL * (self.level - 1)
        if frac > ENEMY_SHIELD_FRACTION_MAX:
            frac = ENEMY_SHIELD_FRACTION_MAX
        # Also clamp to a sensible max within the playfield (leave at least one
        # LED past the shield so the snake-around-shield render has room).
        idx = int(self._pf_len * frac)
        if idx > self._pf_len - 2:
            idx = self._pf_len - 2
        self._enemy_shield_pf_idx = idx

    # ---------- Geometry helpers ----------

    def _pf_to_strip(self, pf_idx):
        """Convert a playfield index (0 = home end) to a strip index."""
        return self._pf_start + pf_idx

    def _start_length(self, level):
        base = int(self._pf_len * START_FRACTION)
        extra = GROW_PER_LEVEL * (level - 1)
        cap = int(self._pf_len * MAX_FRACTION)
        return max(1, min(base + extra, cap))

    def _grow_interval_ms(self, level):
        v = GROW_TICK_MS - GROW_SPEEDUP_MS * (level - 1)
        return max(GROW_TICK_MIN_MS, v)

    # ---------- State entries ----------

    def _enter_intro_flash(self, now):
        self._set_state("intro_flash")
        self._intro_flashes_remaining = self.level  # flash N times total (off->on cycles)
        self._intro_flash_on = False
        # Schedule first toggle (off->on) immediately
        self._intro_flash_next_toggle = now

    def _enter_intro_highscore(self, now):
        self._set_state("intro_highscore")
        # Re-flash level number on top of green highscore: same N flashes,
        # then hold for INTRO_HS_HOLD_MS once flashes finish.
        self._intro_flashes_remaining = self.level
        self._intro_flash_on = False
        self._intro_flash_next_toggle = now
        self._intro_hs_until = 0  # set after flashes finish

    def _enter_intro_materialize(self, now):
        self._set_state("intro_materialize")
        self.snake_balls = []
        target_len = self._start_length(self.level)
        self._intro_target_len = target_len
        self._intro_mat_built = 0
        self._intro_mat_next_ms = now

    def _enter_playing(self, now):
        self._set_state("playing")
        # head is at the position furthest from far end among current snake
        # Snake fills from far end inward; head is the home-side end of the block.
        # If snake length is L and tail (last ball) is at pf_idx (pf_len - 1),
        # then head is at pf_idx (pf_len - L). We've stored snake_balls so that
        # snake_balls[0] is the head ball; snake_balls[-1] is the tail ball.
        self.head_pf_idx = self._pf_len - len(self.snake_balls)
        self.balls = []
        self._last_shot_ms = 0
        self._next_grow_ms = time.ticks_add(now, self._grow_interval_ms(self.level))

    def _enter_win_anim(self, now):
        self._set_state("win_anim")
        self._win_sweep_idx = 0
        self._win_next_step_ms = now
        self._win_fade_started = False
        self._win_fade_start_ms = 0

    def _enter_gameover_anim(self, now):
        self._set_state("gameover_anim")
        # March-home base cadence: a fraction of the level's grow interval.
        # Each dropped ball increments _go_speed; effective interval is
        # _go_base_ms / _go_speed (so speed=2 is twice as fast as start).
        self._go_base_ms = max(1, self._grow_interval_ms(self.level) // GAMEOVER_MARCH_SPEEDUP)
        self._go_speed = 1
        self._go_next_march_ms = time.ticks_add(now, self._go_base_ms)

    def _enter_inactive(self, save):
        if save and self.level > self.highscore:
            self.highscore = self.level
            _save_highscore(self.highscore)
        # Clear playfield so nothing lingers; main loop will resume saved mode next tick.
        self._clear_playfield_only()
        self.led.strip.write()
        self.snake_balls = []
        self.balls = []
        self.level = 0
        self._set_state("inactive")

    # ---------- State advancement ----------

    def _advance_state(self, now):
        s = self.state
        if s == "intro_flash":
            self._advance_intro_flash(now, with_highscore=False)
        elif s == "intro_highscore":
            self._advance_intro_flash(now, with_highscore=True)
        elif s == "intro_materialize":
            self._advance_intro_materialize(now)
        elif s == "playing":
            self._advance_playing(now)
        elif s == "win_anim":
            self._advance_win_anim(now)
        elif s == "gameover_anim":
            self._advance_gameover_anim(now)

    def _advance_intro_flash(self, now, with_highscore):
        if self._intro_flashes_remaining > 0 or self._intro_flash_on:
            if time.ticks_diff(now, self._intro_flash_next_toggle) >= 0:
                if not self._intro_flash_on:
                    # Turn on
                    self._intro_flash_on = True
                    self._intro_flash_next_toggle = time.ticks_add(now, INTRO_FLASH_ON_MS)
                else:
                    # Turn off; consumes one flash
                    self._intro_flash_on = False
                    self._intro_flashes_remaining -= 1
                    self._intro_flash_next_toggle = time.ticks_add(now, INTRO_FLASH_OFF_MS)
            return
        # Flashes done.
        if not with_highscore:
            # Move on to highscore overlay (regardless of whether highscore > 0;
            # if 0, nothing green renders but the flash repeats — gives consistent timing).
            self._enter_intro_highscore(now)
        else:
            # Already in intro_highscore: hold for INTRO_HS_HOLD_MS, then materialize.
            if self._intro_hs_until == 0:
                self._intro_hs_until = time.ticks_add(now, INTRO_HS_HOLD_MS)
            elif time.ticks_diff(now, self._intro_hs_until) >= 0:
                self._enter_intro_materialize(now)

    def _advance_intro_materialize(self, now):
        if self._intro_mat_built >= self._intro_target_len:
            self._enter_playing(now)
            return
        if time.ticks_diff(now, self._intro_mat_next_ms) >= 0:
            # The very last ball materialized is inserted at index 0 — that
            # becomes the snake's head when play starts. Force that ball to
            # always be a primary (R/G/B) so the player can match it from
            # the first moment, regardless of level palette.
            is_last = (self._intro_mat_built == self._intro_target_len - 1)
            palette = _COLORS if is_last else _palette_for_level(self.level)
            self.snake_balls.insert(0, random.choice(palette))
            self._intro_mat_built += 1
            self._intro_mat_next_ms = time.ticks_add(now, INTRO_MATERIALIZE_MS)

    def _advance_playing(self, now):
        # Grow timer
        if time.ticks_diff(now, self._next_grow_ms) >= 0:
            self._grow_snake()
            if self.head_pf_idx <= self._barrier_pf_idx:
                self._enter_gameover_anim(now)
                return
            self._next_grow_ms = time.ticks_add(now, self._grow_interval_ms(self.level))

        # Ball stepping
        shield_hit = self._step_balls(now)

        # Win conditions: shield struck, or snake fully cleared.
        if shield_hit or not self.snake_balls:
            self._enter_win_anim(now)

    def _grow_snake(self):
        # Append new random ball at the far-end tail; whole block shifts toward home
        # (head_pf_idx decreases by 1). Palette widens with level.
        self.snake_balls.append(random.choice(_palette_for_level(self.level)))
        self.head_pf_idx -= 1

    def _launch_ball(self, color, now):
        # Debounce: minimum spacing between consecutive launches
        if self._last_shot_ms != 0:
            if time.ticks_diff(now, self._last_shot_ms) < BALL_DEBOUNCE_MS:
                return
        ball = {"color": color, "pf_idx": 0, "last_step_ms": now}
        self.balls.append(ball)
        self._last_shot_ms = now
        self._game_shots_fired += 1

    def _shield_exposed(self):
        # Enemy shield is shootable as soon as the snake's head has reached
        # the shield position. Visually the snake-around-shield render shifts
        # any ball at or past the shield by +1, so when head_pf_idx ==
        # shield_idx the player sees the shield in front of the head — and
        # expects to hit it. Snake empty → trivially exposed.
        if not self.snake_balls:
            return True
        return self.head_pf_idx >= self._enemy_shield_pf_idx

    def _step_balls(self, now):
        if not self.balls:
            return False
        head_pf = self.head_pf_idx if self.snake_balls else self._pf_len  # past-the-end
        survivors = []
        shield_hit = False
        # Sort by pf_idx desc so we resolve the foremost ball first; prevents two
        # balls from claiming the same head in a single tick.
        self.balls.sort(key=lambda b: -b["pf_idx"])
        for b in self.balls:
            # Step as many LEDs as elapsed time allows (catch-up)
            while time.ticks_diff(now, b["last_step_ms"]) >= BALL_TICK_MS:
                b["pf_idx"] += 1
                b["last_step_ms"] = time.ticks_add(b["last_step_ms"], BALL_TICK_MS)
                # Enemy shield: if exposed and ball reaches it, level won.
                if (b["pf_idx"] >= self._enemy_shield_pf_idx
                        and self._shield_exposed()):
                    shield_hit = True
                    b = None
                    break
                if self.snake_balls and b["pf_idx"] >= head_pf:
                    self._resolve_ball_hit(b)
                    head_pf = self.head_pf_idx if self.snake_balls else self._pf_len
                    b = None
                    break
                if b["pf_idx"] > self._pf_len - 1:
                    # Off the end (snake gone); discard.
                    b = None
                    break
            if b is not None:
                survivors.append(b)
        self.balls = survivors
        return shield_hit

    def _resolve_ball_hit(self, ball):
        if not self.snake_balls:
            return
        head_color = self.snake_balls[0]
        if ball["color"] == head_color:
            # Match: remove head; snake shifts away from home (head_pf_idx += 1).
            self.snake_balls.pop(0)
            self.head_pf_idx += 1
        else:
            if self.level >= BALL_BECOMES_HEAD_LEVEL:
                # Wrong-color ball becomes the new head
                self.snake_balls.insert(0, ball["color"])
                self.head_pf_idx -= 1

    def _advance_win_anim(self, now):
        # Phase 1: sweep a bright pulse from home end to far end
        if not self._win_fade_started:
            if time.ticks_diff(now, self._win_next_step_ms) >= 0:
                self._win_sweep_idx += 1
                self._win_next_step_ms = time.ticks_add(now, WIN_ANIM_STEP_MS)
                if self._win_sweep_idx >= self._pf_len:
                    self._win_fade_started = True
                    self._win_fade_start_ms = now
            return
        # Phase 2: fade
        if time.ticks_diff(now, self._win_fade_start_ms) >= WIN_FADE_MS:
            self.level += 1
            self._recompute_shield_idx()
            self._enter_intro_flash(now)

    def _advance_gameover_anim(self, now):
        # Snake marches home — no new tail balls. Each ball that drops off the
        # home edge increments _go_speed by 1, so the march accelerates as the
        # snake unloads.
        if self.snake_balls:
            if time.ticks_diff(now, self._go_next_march_ms) >= 0:
                self.head_pf_idx -= 1
                # snake_balls[k] sits at head_pf_idx + k; head (k=0) is home-side.
                while self.snake_balls and self.head_pf_idx < 0:
                    self.snake_balls.pop(0)
                    self.head_pf_idx += 1
                    self._go_speed += 1
                step_ms = max(1, self._go_base_ms // self._go_speed)
                self._go_next_march_ms = time.ticks_add(now, step_ms)
            return

        # Snake fully gone: save highscore if beaten, return to inactive.
        self._enter_inactive(save=True)

    # ---------- Render ----------

    def _clear_playfield_only(self):
        # Clear LEDs in the addressable strip range, but never touch LED 0
        # (status LED). Set everything from LED_START_OFFSET to NUM_LEDS-1
        # to black so previous-mode pixels don't leak.
        for i in range(LED_START_OFFSET, NUM_LEDS):
            self.led.strip[i] = COLOR_BLACK

    def _set_pf(self, pf_idx, rgb):
        if pf_idx < 0 or pf_idx >= self._pf_len:
            return
        self.led.strip[self._pf_to_strip(pf_idx)] = rgb

    def _crackle_rgb(self, brightness):
        """White/yellow crackle: hue 40-60 (warm yellow/amber), random
        saturation 0..100 so it flickers from pure white through to saturated
        yellow. Brightness is the configured shield brightness (0..1)."""
        hue = random.randint(40, 60)
        sat = random.randint(0, 100)
        return self.led.hsv_to_rgb(hue, sat, brightness * 100)

    def _render(self):
        if not self.led.enabled:
            return

        # 1. Clear playfield (and any LEDs outside it within the strip range)
        self._clear_playfield_only()

        s = self.state

        # 2. Underlay: highscore green during intro_highscore
        if s == "intro_highscore":
            self._render_highscore()

        # 3. Snake (paint snake balls at their LED positions)
        if s in ("intro_materialize", "playing", "win_anim", "gameover_anim"):
            self._render_snake(s)

        # 4. In-flight balls (with brightness ramp)
        if self.balls and s == "playing":
            self._render_balls()

        # 5. Shields (home barrier + enemy shield) crackle with random energy.
        # Drawn AFTER the snake so the snake passes "under" them visually.
        # Shootability of the enemy shield is independent (handled in
        # _step_balls via _shield_exposed); rendering is purely cosmetic.
        if s in ("intro_materialize", "playing", "intro_highscore", "intro_flash"):
            self._set_pf(self._barrier_pf_idx, self._crackle_rgb(BARRIER_BRIGHTNESS))
            self._set_pf(self._enemy_shield_pf_idx, self._crackle_rgb(ENEMY_SHIELD_BRIGHTNESS))

        # 6. State-specific overlays
        if s == "intro_flash" and self._intro_flash_on:
            self._render_level_flash()
        elif s == "intro_highscore" and self._intro_flash_on:
            self._render_level_flash()
        elif s == "win_anim":
            self._render_win_overlay()

        # 7. Push to hardware
        self.led.strip.write()

    def _render_highscore(self):
        # Highscore green: H LEDs from the far end inward.
        h = self.highscore
        if h <= 0:
            return
        for k in range(h):
            pf_idx = self._pf_len - 1 - k
            if pf_idx < 0:
                break
            self._set_pf(pf_idx, COLOR_HIGHSCORE)

    def _render_level_flash(self):
        # N LEDs at the far end, white. N = current level.
        n = self.level
        for k in range(n):
            pf_idx = self._pf_len - 1 - k
            if pf_idx < 0:
                break
            self._set_pf(pf_idx, COLOR_WHITE)

    def _render_snake(self, state):
        if state == "intro_materialize":
            # Materializing portion: the most recent self._intro_mat_built balls
            # fill from far end inward.
            built = self._intro_mat_built
            for k in range(built):
                ball = self.snake_balls[built - 1 - k] if (built - 1 - k) < len(self.snake_balls) else None
                if ball is None:
                    break
                pf_idx = self._pf_len - 1 - k
                if pf_idx < 0:
                    break
                self._set_pf(pf_idx, _COLOR_MAP[ball])
            return
        # Playing/win/gameover: snake_balls[0]=head at head_pf_idx,
        # snake_balls[k] at head_pf_idx + k.
        # Visual cheat: the enemy shield occupies its own LED. Any tail-side
        # snake ball that would land at or past the shield position is
        # rendered shifted +1 toward the far end, so the shield slots
        # "between" the head-side and tail-side halves of the snake. This is
        # geometrically incorrect (the snake gets one LED longer visually)
        # but keeps the head ball visible whenever it crosses the shield.
        shield_idx = self._enemy_shield_pf_idx
        for k, c in enumerate(self.snake_balls):
            pf_idx = self.head_pf_idx + k
            if pf_idx >= shield_idx:
                pf_idx += 1
            if 0 <= pf_idx < self._pf_len:
                self._set_pf(pf_idx, _COLOR_MAP[c])

    def _render_balls(self):
        b_idx = self._barrier_pf_idx
        for ball in self.balls:
            pf_idx = ball["pf_idx"]
            base = _COLOR_MAP[ball["color"]]
            if pf_idx <= b_idx:
                denom = max(1, b_idx)
                factor = BARRIER_BRIGHTNESS + (1.0 - BARRIER_BRIGHTNESS) * (pf_idx / denom)
                if factor > 1.0:
                    factor = 1.0
                rgb = _scale(base, factor)
            else:
                rgb = base
            self._set_pf(pf_idx, rgb)

    def _render_win_overlay(self):
        if self._win_fade_started:
            # Fade from white to black over WIN_FADE_MS
            elapsed = time.ticks_diff(time.ticks_ms(), self._win_fade_start_ms)
            if elapsed < 0:
                elapsed = 0
            if elapsed >= WIN_FADE_MS:
                return
            f = 1.0 - (elapsed / WIN_FADE_MS)
            rgb = _scale(COLOR_WHITE, f)
            for pf_idx in range(self._pf_len):
                self._set_pf(pf_idx, rgb)
            return
        # Sweep phase: paint a small bright head with a fading trail
        head = self._win_sweep_idx
        for k in range(8):
            pf_idx = head - k
            if pf_idx < 0:
                break
            f = 1.0 - (k / 8.0)
            self._set_pf(pf_idx, _scale(COLOR_WHITE, f))

