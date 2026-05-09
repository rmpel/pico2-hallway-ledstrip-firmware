# Simon Says — game 2.
#
# Sequence-memory game on the LED strip. The strip plays a growing sequence
# of R/G/B/Y colors; the player must repeat the sequence by pressing the
# matching colored buttons. Game ends on a wrong press or timeout. Score is
# the longest round the player completed correctly.
#
# Tunables live under /settings.json -> "game2" (see _GAME2_DEFAULTS) and
# are read once at module import — same convention as lib/game.py.

import time
import random

from config import NUM_LEDS, LED_START_OFFSET, LED_BRIGHTNESS_MAX
from game_common import (
    BaseGame,
    load_game_overrides,
    load_highscore_dict,
    save_highscore_dict,
    resolve_button_map,
)


# ---------- Tunables ----------

_GAME2_DEFAULTS = {
    "playfield_start_led": 0,
    "playfield_end_led": -1,        # -1 = NUM_LEDS - 1
    "flash_on_ms": 750,             # sequence playback: each color ON
    "flash_off_ms": 250,            # sequence playback: gap between colors
    "input_timeout_ms": 3000,       # per-press countdown (whole seconds)
    "press_feedback_ms": 150,       # per-press playfield flash
    "result_flash_ms": 250,         # red/green flash on/off duration
    "result_flash_count": 3,        # number of red/green flashes
    "score_display_ms": 3000,       # how long the score is shown
}


_overrides = load_game_overrides("game2")


def _g(key):
    return _overrides.get(key, _GAME2_DEFAULTS[key])


PLAYFIELD_START_LED = _g("playfield_start_led")
PLAYFIELD_END_LED = _g("playfield_end_led")
FLASH_ON_MS = _g("flash_on_ms")
FLASH_OFF_MS = _g("flash_off_ms")
INPUT_TIMEOUT_MS = max(1000, (_g("input_timeout_ms") // 1000) * 1000)
PRESS_FEEDBACK_MS = _g("press_feedback_ms")
RESULT_FLASH_MS = _g("result_flash_ms")
RESULT_FLASH_COUNT = _g("result_flash_count")
SCORE_DISPLAY_MS = _g("score_display_ms")


HIGHSCORE_FILE = "/game2.json"
HIGHSCORE_DEFAULT = {"highscore": 0}


# ---------- Colors ----------

COLOR_R = (LED_BRIGHTNESS_MAX, 0, 0)
COLOR_G = (0, LED_BRIGHTNESS_MAX, 0)
COLOR_B = (0, 0, LED_BRIGHTNESS_MAX)
COLOR_Y = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, 0)
COLOR_WHITE = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX)
COLOR_BLACK = (0, 0, 0)

_COLOR_MAP = {"R": COLOR_R, "G": COLOR_G, "B": COLOR_B, "Y": COLOR_Y}
_COLORS = ("R", "G", "B", "Y")


# ---------- Default button map ----------
# Per §5.8: 2x2 keypad — Red=on, Blue=auto, Yellow=f1, Green=f2.
_SIMON_ACTION_TO_COLOR = {
    "input_red": "R",
    "input_green": "G",
    "input_blue": "B",
    "input_yellow": "Y",
}
_DEFAULT_SIMON_BUTTON_TO_COLOR = {
    "on":   "R",
    "auto": "B",
    "f1":   "Y",
    "f2":   "G",
}


def resolve_simon_button_map():
    """Read /settings.json -> game2.buttons and produce a button->color dict
    suitable for the button handler's active-game color map. Falls back to
    the §5.8 defaults for any missing entries."""
    raw = _overrides.get("buttons") if isinstance(_overrides.get("buttons"), dict) else None
    return resolve_button_map(raw, _SIMON_ACTION_TO_COLOR, _DEFAULT_SIMON_BUTTON_TO_COLOR)


class SimonGame(BaseGame):
    def __init__(self, led, storage, registry):
        super().__init__(led, storage, registry)

        # Highscore (in-memory cache; persisted in /game2.json).
        hs = load_highscore_dict(HIGHSCORE_FILE, HIGHSCORE_DEFAULT)
        self.highscore = int(hs.get("highscore", 0) or 0)

        # Playfield bounds (resolved on each begin in case strip count changes
        # between settings reads). LEDs are [start, end] inclusive.
        self._pf_start = 0
        self._pf_end = 0
        self._pf_len = 0

        # Sequence state
        self.sequence = []          # list of color letters, e.g. ["R","G","B"]
        self._seq_play_idx = 0      # which sequence index is currently being shown
        self._seq_phase = "on"      # "on" or "off" within the current step
        self._seq_next_toggle = 0
        # Input phase
        self._input_idx = 0         # how many correct presses so far this round
        self._countdown_started = 0
        # press_feedback state: paint the pressed color across the playfield
        # for PRESS_FEEDBACK_MS, then transition based on _pending_after_feedback.
        self._press_feedback_color = None   # "R" / "G" / "B" / "Y"
        self._press_feedback_until = 0
        # Where to go after press_feedback expires:
        #   "continue"      -> back to awaiting_input (more presses needed)
        #   "correct_flash" -> green 3x then next round
        #   "wrong_flash"   -> red 3x then score_display
        self._pending_after_feedback = None
        # Result flash (red wrong / green correct)
        self._result_color = None   # "R" wrong / "G" correct
        self._result_flashes_remaining = 0
        self._result_flash_on = False
        self._result_next_toggle = 0
        # Score display
        self._score_until = 0

        # Pending input queue (cross-thread; press_edge from button handler).
        self._pending_inputs = []

        # Round number = len(sequence). Score = longest fully-completed round.
        self._score = 0

    # ---------- Public API (cross-thread) ----------

    def input(self, color):
        """Queue a player input. Accepted colors: R/G/B/Y. Other inputs
        silently drop. Accepted while we're awaiting input AND while press
        feedback is showing (so rapid double-taps that land mid-feedback
        aren't lost). Presses during sequence playback / result flashes /
        score display ARE dropped — buffering those would be a foot-gun."""
        if color not in _COLOR_MAP:
            return
        with self._lock:
            if self.state in ("awaiting_input", "press_feedback"):
                self._pending_inputs.append(color)

    def get_phase(self):
        # Public phase string for the web /api/game2/status endpoint.
        s = self.state
        if s in ("playing_sequence", "awaiting_input", "score_display"):
            return s
        if s in ("press_feedback", "wrong_flash", "correct_flash"):
            return "feedback"
        return "inactive"

    def get_status(self):
        return {
            "active": self.is_active(),
            "round": len(self.sequence),
            "score": self._score,
            "highscore": self.highscore,
            "phase": self.get_phase(),
        }

    # ---------- BaseGame hooks ----------

    def _drain_pending_inputs(self, now):
        with self._lock:
            do_start = self._pending_start
            do_stop = self._pending_stop
            self._pending_start = False
            self._pending_stop = False

        if do_stop:
            self._enter_inactive(save=False)
            return

        if do_start and self.state == "inactive":
            if not self._try_begin():
                # Another game owns the strip; silently drop.
                return
            self._begin_game(now)

        # Pull inputs only when we can actually act on them. Inputs that
        # arrive during press_feedback are intentionally left queued so they
        # get handled the next time we re-enter awaiting_input.
        if self.state != "awaiting_input":
            return

        with self._lock:
            inputs = self._pending_inputs
            self._pending_inputs = []
        if not inputs:
            return
        # Process inputs sequentially. The first press transitions to
        # press_feedback; the rest must stay queued for when we re-enter
        # awaiting_input (otherwise rapid double-presses get silently lost).
        for i in range(len(inputs)):
            if self.state != "awaiting_input":
                with self._lock:
                    self._pending_inputs = inputs[i:] + self._pending_inputs
                break
            self._handle_input(inputs[i], now)

    def _advance_state(self, now):
        s = self.state
        if s == "playing_sequence":
            self._advance_playing_sequence(now)
        elif s == "awaiting_input":
            self._advance_awaiting_input(now)
        elif s == "press_feedback":
            self._advance_press_feedback(now)
        elif s == "wrong_flash":
            self._advance_result_flash(now, after_wrong=True)
        elif s == "correct_flash":
            self._advance_result_flash(now, after_wrong=False)
        elif s == "score_display":
            if time.ticks_diff(now, self._score_until) >= 0:
                self._enter_inactive(save=True)

    # ---------- Lifecycle ----------

    def _begin_game(self, now):
        self._refresh_playfield_bounds()
        self.sequence = [random.choice(_COLORS)]
        self._score = 0
        self._enter_playing_sequence(now)

    def _refresh_playfield_bounds(self):
        start = PLAYFIELD_START_LED
        end = PLAYFIELD_END_LED if PLAYFIELD_END_LED >= 0 else NUM_LEDS - 1
        if start < LED_START_OFFSET:
            start = LED_START_OFFSET
        if end > NUM_LEDS - 1:
            end = NUM_LEDS - 1
        if end < start:
            end = start
        self._pf_start = start
        self._pf_end = end
        self._pf_len = end - start + 1

    def _enter_playing_sequence(self, now):
        self._set_state("playing_sequence")
        self._seq_play_idx = 0
        self._seq_phase = "on"
        # New round → reset input position. (Done here, NOT in
        # _enter_awaiting_input — that one is also re-entered mid-round after
        # a correct-press feedback, where the input position must persist.)
        self._input_idx = 0
        # The first ON shows immediately — schedule the off-toggle.
        self._seq_next_toggle = time.ticks_add(now, FLASH_ON_MS)
        # Debug: log the full sequence so we can verify prefix persistence.
        print("simon: round", len(self.sequence), "sequence:", "".join(self.sequence))

    def _enter_awaiting_input(self, now):
        # Note: _input_idx is intentionally NOT reset here. The mid-round
        # press_feedback->continue path re-enters this state preserving idx.
        # Round-start reset is in _enter_playing_sequence.
        self._set_state("awaiting_input")
        self._countdown_started = now

    def _enter_press_feedback(self, now, color, after):
        """Show the pressed color across the playfield for PRESS_FEEDBACK_MS,
        then transition to `after` ("continue", "correct_flash", "wrong_flash")."""
        self._set_state("press_feedback")
        self._press_feedback_color = color
        self._press_feedback_until = time.ticks_add(now, PRESS_FEEDBACK_MS)
        self._pending_after_feedback = after

    def _enter_wrong_flash(self, now):
        self._set_state("wrong_flash")
        self._result_color = "R"
        self._result_flashes_remaining = RESULT_FLASH_COUNT
        self._result_flash_on = True
        # First ON shows immediately; schedule the off toggle.
        self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)

    def _enter_correct_flash(self, now):
        self._set_state("correct_flash")
        self._result_color = "G"
        self._result_flashes_remaining = RESULT_FLASH_COUNT
        self._result_flash_on = True
        self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)

    def _enter_score_display(self, now):
        self._set_state("score_display")
        self._score_until = time.ticks_add(now, SCORE_DISPLAY_MS)

    def _enter_inactive(self, save):
        if save and self._score > self.highscore:
            self.highscore = self._score
            save_highscore_dict(HIGHSCORE_FILE, {"highscore": int(self.highscore)})
        # Clear playfield so nothing lingers; main loop will resume saved
        # mode next tick.
        self._clear_strip()
        self.led.strip.write()
        self.sequence = []
        self._pending_inputs = []
        self._set_state("inactive")

    # ---------- Sequence playback ----------

    def _advance_playing_sequence(self, now):
        if time.ticks_diff(now, self._seq_next_toggle) < 0:
            return
        if self._seq_phase == "on":
            # End of ON; switch to OFF.
            self._seq_phase = "off"
            self._seq_next_toggle = time.ticks_add(now, FLASH_OFF_MS)
        else:
            # End of OFF; advance to next color.
            self._seq_play_idx += 1
            if self._seq_play_idx >= len(self.sequence):
                # Sequence done — wait for player input.
                self._enter_awaiting_input(now)
                return
            self._seq_phase = "on"
            self._seq_next_toggle = time.ticks_add(now, FLASH_ON_MS)

    # ---------- Input phase ----------

    def _handle_input(self, color, now):
        expected = self.sequence[self._input_idx]
        if color != expected:
            # Wrong press. Score = longest fully-completed round.
            self._score = max(0, len(self.sequence) - 1)
            # Show the pressed color first so the player gets feedback that
            # the button registered, then the red 3x flash kicks in.
            self._enter_press_feedback(now, color, "wrong_flash")
            return
        # Correct press. Show the pressed color, then either continue (more
        # presses needed) or transition to the green 3x flash (last press).
        self._input_idx += 1
        if self._input_idx >= len(self.sequence):
            # Round complete. Score = round just finished.
            self._score = len(self.sequence)
            self._enter_press_feedback(now, color, "correct_flash")
        else:
            self._enter_press_feedback(now, color, "continue")

    def _advance_awaiting_input(self, now):
        elapsed = time.ticks_diff(now, self._countdown_started)
        if elapsed >= INPUT_TIMEOUT_MS:
            # Timeout. Score = longest fully-completed round = current round
            # number minus 1 (the player did NOT finish the current round).
            self._score = max(0, len(self.sequence) - 1)
            self._enter_wrong_flash(now)

    def _advance_press_feedback(self, now):
        if time.ticks_diff(now, self._press_feedback_until) < 0:
            return
        after = self._pending_after_feedback
        self._press_feedback_color = None
        self._pending_after_feedback = None
        if after == "correct_flash":
            self._enter_correct_flash(now)
        elif after == "wrong_flash":
            self._enter_wrong_flash(now)
        else:
            # "continue" — back to awaiting_input with a fresh countdown for
            # the next press.
            self._enter_awaiting_input(now)

    # ---------- Result flash ----------

    def _advance_result_flash(self, now, after_wrong):
        if time.ticks_diff(now, self._result_next_toggle) < 0:
            return
        if self._result_flash_on:
            # End of ON; go OFF.
            self._result_flash_on = False
            self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)
            self._result_flashes_remaining -= 1
        else:
            # End of OFF.
            if self._result_flashes_remaining <= 0:
                if after_wrong:
                    self._enter_score_display(now)
                else:
                    # Correct: grow sequence and play again.
                    self.sequence.append(random.choice(_COLORS))
                    self._enter_playing_sequence(now)
                return
            # Next ON.
            self._result_flash_on = True
            self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)

    # ---------- Render ----------

    def _clear_strip(self):
        if not self.led.enabled:
            return
        # Clear LEDs in the addressable strip range, but never touch LED 0
        # if it's the status LED (matches game.py convention).
        for i in range(LED_START_OFFSET, NUM_LEDS):
            self.led.strip[i] = COLOR_BLACK

    def _fill_playfield(self, rgb):
        for i in range(self._pf_start, self._pf_end + 1):
            self.led.strip[i] = rgb

    def _render(self):
        if not self.led.enabled:
            return
        self._clear_strip()
        s = self.state

        if s == "playing_sequence":
            if self._seq_phase == "on" and self._seq_play_idx < len(self.sequence):
                color = self.sequence[self._seq_play_idx]
                self._fill_playfield(_COLOR_MAP[color])

        elif s == "awaiting_input":
            self._render_countdown(time.ticks_ms())

        elif s == "press_feedback":
            if self._press_feedback_color is not None:
                self._fill_playfield(_COLOR_MAP[self._press_feedback_color])

        elif s in ("wrong_flash", "correct_flash"):
            if self._result_flash_on:
                color = COLOR_R if s == "wrong_flash" else COLOR_G
                self._fill_playfield(color)
            # else: dark — handled by _clear_strip.

        elif s == "score_display":
            self._render_score()

        self.led.strip.write()

    def _render_countdown(self, now):
        """Render the per-press countdown.

        The countdown lights N+1 LEDs at t=0 (where N = INPUT_TIMEOUT_MS / 1000),
        pops one at t=250ms, then one per full-second boundary until 0 lit
        at t=N*1000ms. LEDs are placed in the center of the playfield. With
        even/odd parity mismatches between strip length and LED count, prefer
        the home-side pair (matches §5.4 / §5.4a)."""
        n_seconds = INPUT_TIMEOUT_MS // 1000
        elapsed = time.ticks_diff(now, self._countdown_started)
        # Initial LED count = N+1; first pop at +250ms; subsequent pops at
        # +1000, +2000, ... +N*1000.
        if elapsed < 250:
            lit = n_seconds + 1
        elif elapsed < 1000:
            lit = n_seconds
        else:
            # After 1s, every full second pops one more.
            popped_post_1s = (elapsed - 1000) // 1000 + 1
            lit = n_seconds - popped_post_1s
            if lit < 0:
                lit = 0
        if lit <= 0 or self._pf_len <= 0:
            return
        # Center `lit` LEDs in [_pf_start, _pf_end].
        if lit >= self._pf_len:
            for i in range(self._pf_start, self._pf_end + 1):
                self.led.strip[i] = COLOR_WHITE
            return
        # Home-side preference: with odd extra space, the gap goes to the far end.
        extra = self._pf_len - lit
        offset_from_home = extra // 2
        block_start = self._pf_start + offset_from_home
        for k in range(lit):
            self.led.strip[block_start + k] = COLOR_WHITE

    def _render_score(self):
        # N white LEDs from the FAR end (matching Snake's "far = away from home"
        # convention). N exceeds playfield length → fill entire playfield.
        n = self._score
        if n <= 0:
            return
        if n >= self._pf_len:
            for i in range(self._pf_start, self._pf_end + 1):
                self.led.strip[i] = COLOR_WHITE
            return
        for k in range(n):
            i = self._pf_end - k
            if i < self._pf_start:
                break
            self.led.strip[i] = COLOR_WHITE
