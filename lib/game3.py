# Master Mind — game 3.
#
# Code-breaking game on the LED strip. The firmware picks a random secret
# of length L (3..6) from the 6-color palette R/G/B/Y/C/M; the player has
# up to 10 guesses to match it. Each guess is rendered as a row at the
# home end (newest first), with feedback pegs (greens = right color/right
# spot, reds = right color/wrong spot). Win flashes green; loss reveals
# the secret for 5s.
#
# Tunables live under /settings.json -> "game3" (see _GAME3_DEFAULTS) and
# are read once at module import — same convention as lib/game.py and
# lib/game2.py.

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

_GAME3_DEFAULTS = {
    "playfield_start_led": 0,
    "playfield_end_led": -1,        # -1 = NUM_LEDS - 1
    "default_length": 4,            # initial selection in length-select
    "min_length": 3,
    "max_length": 6,
    "max_guesses": 10,
    "feedback_hold_ms": 5000,       # post-evaluation row display before next input
    "reveal_hold_ms": 5000,         # how long the secret is shown on loss
    "result_flash_ms": 250,         # win-flash on/off duration
    "result_flash_count": 3,        # number of win flashes
    "separator_brightness": 0.20,   # white separator brightness in [0,1]
}


_overrides = load_game_overrides("game3")


def _g(key):
    return _overrides.get(key, _GAME3_DEFAULTS[key])


PLAYFIELD_START_LED = _g("playfield_start_led")
PLAYFIELD_END_LED = _g("playfield_end_led")
DEFAULT_LENGTH = _g("default_length")
MIN_LENGTH = _g("min_length")
MAX_LENGTH = _g("max_length")
MAX_GUESSES = _g("max_guesses")
FEEDBACK_HOLD_MS = _g("feedback_hold_ms")
REVEAL_HOLD_MS = _g("reveal_hold_ms")
RESULT_FLASH_MS = _g("result_flash_ms")
RESULT_FLASH_COUNT = _g("result_flash_count")
SEPARATOR_BRIGHTNESS = _g("separator_brightness")


# Defensive clamps on import-time values: storage sanitizer should already
# enforce these, but if a user hand-edits /settings.json we still want to
# stay inside [3,6] / sane ranges.
if MIN_LENGTH < 3:
    MIN_LENGTH = 3
if MAX_LENGTH > 6:
    MAX_LENGTH = 6
if MAX_LENGTH < MIN_LENGTH:
    MAX_LENGTH = MIN_LENGTH
if DEFAULT_LENGTH < MIN_LENGTH:
    DEFAULT_LENGTH = MIN_LENGTH
elif DEFAULT_LENGTH > MAX_LENGTH:
    DEFAULT_LENGTH = MAX_LENGTH
if SEPARATOR_BRIGHTNESS < 0.0:
    SEPARATOR_BRIGHTNESS = 0.0
elif SEPARATOR_BRIGHTNESS > 1.0:
    SEPARATOR_BRIGHTNESS = 1.0


HIGHSCORE_FILE = "/game3.json"
# Per-length best (fewest guesses to win). 0 = no record yet.
HIGHSCORE_DEFAULT = {"highscore": {"3": 0, "4": 0, "5": 0, "6": 0}}


# ---------- Colors ----------

COLOR_R = (LED_BRIGHTNESS_MAX, 0, 0)
COLOR_G = (0, LED_BRIGHTNESS_MAX, 0)
COLOR_B = (0, 0, LED_BRIGHTNESS_MAX)
COLOR_Y = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, 0)
COLOR_C = (0, LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX)
COLOR_M = (LED_BRIGHTNESS_MAX, 0, LED_BRIGHTNESS_MAX)
COLOR_BLACK = (0, 0, 0)

_sep_v = int(LED_BRIGHTNESS_MAX * SEPARATOR_BRIGHTNESS)
COLOR_SEPARATOR = (_sep_v, _sep_v, _sep_v)

_COLOR_MAP = {
    "R": COLOR_R, "G": COLOR_G, "B": COLOR_B,
    "Y": COLOR_Y, "C": COLOR_C, "M": COLOR_M,
}
_COLORS = ("R", "G", "B", "Y", "C", "M")


# ---------- Default button map ----------
# Per §6.6: every physical button maps to a color.
_MM_ACTION_TO_COLOR = {
    "input_red":     "R",
    "input_green":   "G",
    "input_blue":    "B",
    "input_yellow":  "Y",
    "input_cyan":    "C",
    "input_magenta": "M",
}
_DEFAULT_MM_BUTTON_TO_COLOR = {
    "off":  "R",
    "auto": "G",
    "on":   "B",
    "f1":   "Y",
    "f2":   "C",
    "alt":  "M",
}


def resolve_mastermind_button_map():
    """Read /settings.json -> game3.buttons and produce a button->color dict
    suitable for the button handler's active-game color map. Falls back to
    the §6.6 defaults for any missing entries."""
    raw = _overrides.get("buttons") if isinstance(_overrides.get("buttons"), dict) else None
    return resolve_button_map(raw, _MM_ACTION_TO_COLOR, _DEFAULT_MM_BUTTON_TO_COLOR)


def _score_guess(secret, guess):
    """Standard Mastermind scoring with no double-counting.
    Returns (greens, reds). Greens = right color in right position; reds =
    right color in wrong position, counting each secret/guess slot at most
    once."""
    n = len(secret)
    greens = 0
    # Track unmatched-secret and unmatched-guess colors for the second pass.
    unmatched_s = []
    unmatched_g = []
    for i in range(n):
        if guess[i] == secret[i]:
            greens += 1
        else:
            unmatched_s.append(secret[i])
            unmatched_g.append(guess[i])
    reds = 0
    for c in unmatched_g:
        # Consume one matching color from the unmatched-secret pool.
        for j in range(len(unmatched_s)):
            if unmatched_s[j] == c:
                reds += 1
                # Pop by replacing with sentinel so it can't be re-matched.
                unmatched_s[j] = None
                break
    return greens, reds


class MasterMindGame(BaseGame):
    def __init__(self, led, storage, registry):
        super().__init__(led, storage, registry)

        # Highscore (per length, in-memory cache; persisted in /game3.json).
        hs = load_highscore_dict(HIGHSCORE_FILE, HIGHSCORE_DEFAULT)
        raw_hs = hs.get("highscore") if isinstance(hs, dict) else None
        if not isinstance(raw_hs, dict):
            raw_hs = {}
        self.highscore = {}
        for L in range(MIN_LENGTH, MAX_LENGTH + 1):
            try:
                self.highscore[L] = int(raw_hs.get(str(L), 0) or 0)
            except (TypeError, ValueError):
                self.highscore[L] = 0

        # Last-used length for length-select default-on-second-play. Starts
        # at the configured default_length.
        self._last_length = DEFAULT_LENGTH

        # Playfield bounds (resolved on each begin in case strip count changes
        # between settings reads). LEDs are [start, end] inclusive.
        self._pf_start = 0
        self._pf_end = 0
        self._pf_len = 0

        # Game state
        self._length = DEFAULT_LENGTH
        self._secret = []          # list of color letters
        self._history = []         # list of {"guess": [...], "greens": int, "reds": int}
        self._current_guess = []   # in-progress guess; len() == position to fill next
        self._guesses_used = 0

        # Length-select sub-phase state
        self._select_length = DEFAULT_LENGTH

        # Feedback-hold timing (5s window after a guess is evaluated before
        # the player can submit the next one — overridden by an early press).
        self._feedback_until = 0

        # Reveal-on-loss timing
        self._reveal_until = 0

        # Win flash
        self._result_flashes_remaining = 0
        self._result_flash_on = False
        self._result_next_toggle = 0

        # Pending: explicit start-with-length (web). None = enter length-select.
        self._pending_start_length = None
        # Pending color inputs queued from button handler / web.
        self._pending_inputs = []
        # Pending length-select cycles (F1) and confirmations (F2).
        self._pending_select_cycle = False
        self._pending_select_confirm = False

    # ---------- Public API (cross-thread) ----------

    def start(self, length=None):
        """Queue a start. Pass `length` (3..6) to skip length-select; omit
        to enter the length-select phase."""
        with self._lock:
            self._pending_start = True
            if length is None:
                self._pending_start_length = None
            else:
                try:
                    L = int(length)
                except (TypeError, ValueError):
                    L = DEFAULT_LENGTH
                if L < MIN_LENGTH:
                    L = MIN_LENGTH
                elif L > MAX_LENGTH:
                    L = MAX_LENGTH
                self._pending_start_length = L

    def input(self, color):
        """Queue a color input (R/G/B/Y/C/M). Other inputs silently drop."""
        if color not in _COLOR_MAP:
            return
        with self._lock:
            if self.state in ("awaiting_input", "feedback_hold"):
                self._pending_inputs.append(color)

    def select_cycle(self):
        """Cycle the length-select selection (F1 in length-select mode)."""
        with self._lock:
            if self.state == "length_select":
                self._pending_select_cycle = True

    def select_confirm(self):
        """Confirm the length-select selection (F2 in length-select mode)."""
        with self._lock:
            if self.state == "length_select":
                self._pending_select_confirm = True

    def get_phase(self):
        s = self.state
        if s == "inactive":
            return "inactive"
        if s == "length_select":
            return "length_select"
        if s == "awaiting_input":
            return "awaiting_input"
        if s == "feedback_hold":
            return "feedback_hold"
        if s == "win_flash":
            return "win_flash"
        if s == "reveal":
            return "reveal"
        return s

    def get_status(self):
        # Pad current_guess to length with None for the web view.
        guess_view = list(self._current_guess)
        while len(guess_view) < self._length:
            guess_view.append(None)
        history_view = []
        for h in self._history:
            history_view.append({
                "guess": list(h["guess"]),
                "greens": int(h["greens"]),
                "reds": int(h["reds"]),
            })
        hs_view = {str(L): int(self.highscore.get(L, 0)) for L in range(MIN_LENGTH, MAX_LENGTH + 1)}
        return {
            "active": self.is_active(),
            "phase": self.get_phase(),
            "length": int(self._length),
            "current_guess": guess_view,
            "guesses_used": int(self._guesses_used),
            "max_guesses": int(MAX_GUESSES),
            "history": history_view,
            "highscore": hs_view,
        }

    # ---------- BaseGame hooks ----------

    def _drain_pending_inputs(self, now):
        with self._lock:
            do_start = self._pending_start
            do_stop = self._pending_stop
            start_len = self._pending_start_length
            self._pending_start = False
            self._pending_stop = False
            self._pending_start_length = None
            select_cycle = self._pending_select_cycle
            select_confirm = self._pending_select_confirm
            self._pending_select_cycle = False
            self._pending_select_confirm = False

        if do_stop:
            self._enter_inactive(save=False)
            return

        if do_start and self.state == "inactive":
            if not self._try_begin():
                # Another game owns the strip; silently drop.
                return
            self._begin(now, start_len)

        # Length-select transitions
        if self.state == "length_select":
            if select_cycle:
                self._select_length += 1
                if self._select_length > MAX_LENGTH:
                    self._select_length = MIN_LENGTH
            if select_confirm:
                self._length = self._select_length
                self._last_length = self._length
                self._begin_round(now)

        # Color inputs only matter when we're awaiting a press (or in the
        # post-guess hold, which short-circuits the hold and starts the next
        # guess).
        if self.state not in ("awaiting_input", "feedback_hold"):
            return

        with self._lock:
            inputs = self._pending_inputs
            self._pending_inputs = []
        if not inputs:
            return
        for i in range(len(inputs)):
            if self.state not in ("awaiting_input", "feedback_hold"):
                with self._lock:
                    self._pending_inputs = inputs[i:] + self._pending_inputs
                break
            self._handle_input(inputs[i], now)

    def _advance_state(self, now):
        s = self.state
        if s == "feedback_hold":
            if time.ticks_diff(now, self._feedback_until) >= 0:
                # Hold expired with no early press: continue to next guess
                # (or transition to reveal/inactive if we ran out / won —
                # but those paths set state directly and never enter
                # feedback_hold, so we're always continuing here).
                self._set_state("awaiting_input")
        elif s == "win_flash":
            self._advance_win_flash(now)
        elif s == "reveal":
            if time.ticks_diff(now, self._reveal_until) >= 0:
                self._enter_inactive(save=False)
        # length_select / awaiting_input: nothing time-based to advance.

    # ---------- Lifecycle ----------

    def _begin(self, now, start_length):
        self._refresh_playfield_bounds()
        if start_length is None:
            # Enter length-select; default to last-used length.
            self._select_length = self._last_length
            if self._select_length < MIN_LENGTH:
                self._select_length = MIN_LENGTH
            elif self._select_length > MAX_LENGTH:
                self._select_length = MAX_LENGTH
            self._set_state("length_select")
        else:
            self._length = start_length
            self._last_length = start_length
            self._begin_round(now)

    def _begin_round(self, now):
        # Generate secret, reset guess state.
        self._secret = [random.choice(_COLORS) for _ in range(self._length)]
        self._history = []
        self._current_guess = []
        self._guesses_used = 0
        # Debug: log the secret so we can verify scoring.
        print("mastermind: length", self._length, "secret:", "".join(self._secret))
        self._set_state("awaiting_input")

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

    def _enter_feedback_hold(self, now):
        self._set_state("feedback_hold")
        self._feedback_until = time.ticks_add(now, FEEDBACK_HOLD_MS)

    def _enter_win_flash(self, now):
        self._set_state("win_flash")
        self._result_flashes_remaining = RESULT_FLASH_COUNT
        self._result_flash_on = True
        self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)

    def _enter_reveal(self, now):
        self._set_state("reveal")
        self._reveal_until = time.ticks_add(now, REVEAL_HOLD_MS)

    def _enter_inactive(self, save):
        if save:
            self._save_highscore()
        # Clear playfield so nothing lingers.
        self._clear_strip()
        self.led.strip.write()
        self._secret = []
        self._history = []
        self._current_guess = []
        self._pending_inputs = []
        self._set_state("inactive")

    def _save_highscore(self):
        # Persist all per-length records (the in-memory cache is the source
        # of truth; this is the merge point with disk).
        out = {}
        for L in range(MIN_LENGTH, MAX_LENGTH + 1):
            out[str(L)] = int(self.highscore.get(L, 0))
        save_highscore_dict(HIGHSCORE_FILE, {"highscore": out})

    # ---------- Input phase ----------

    def _handle_input(self, color, now):
        # Early-input override during the post-guess hold: cancel the hold
        # and treat this press as the first slot of the next guess.
        if self.state == "feedback_hold":
            self._set_state("awaiting_input")
            # fall through to record the press

        self._current_guess.append(color)
        if len(self._current_guess) >= self._length:
            self._evaluate_guess(now)

    def _evaluate_guess(self, now):
        guess = list(self._current_guess)
        self._current_guess = []
        greens, reds = _score_guess(self._secret, guess)
        self._history.insert(0, {"guess": guess, "greens": greens, "reds": reds})
        self._guesses_used += 1
        if greens >= self._length:
            # Win — update highscore (fewest guesses to win).
            best = self.highscore.get(self._length, 0)
            if best == 0 or self._guesses_used < best:
                self.highscore[self._length] = self._guesses_used
            self._enter_win_flash(now)
            return
        if self._guesses_used >= MAX_GUESSES:
            # Loss — reveal secret.
            self._enter_reveal(now)
            return
        # Otherwise: hold the row for FEEDBACK_HOLD_MS, then resume input.
        self._enter_feedback_hold(now)

    # ---------- Win flash ----------

    def _advance_win_flash(self, now):
        if time.ticks_diff(now, self._result_next_toggle) < 0:
            return
        if self._result_flash_on:
            self._result_flash_on = False
            self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)
            self._result_flashes_remaining -= 1
        else:
            if self._result_flashes_remaining <= 0:
                self._enter_inactive(save=True)
                return
            self._result_flash_on = True
            self._result_next_toggle = time.ticks_add(now, RESULT_FLASH_MS)

    # ---------- Render ----------

    def _clear_strip(self):
        if not self.led.enabled:
            return
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

        if s == "length_select":
            self._render_length_select()

        elif s == "win_flash":
            if self._result_flash_on:
                # Flash green over the playfield; per §6.8 mirror Simon.
                self._fill_playfield((0, LED_BRIGHTNESS_MAX, 0))

        elif s == "reveal":
            self._render_rows(secret_revealed=True)

        elif s in ("awaiting_input", "feedback_hold"):
            self._render_rows(secret_revealed=False)

        # inactive: strip is already cleared; nothing else to draw.

        self.led.strip.write()

    def _render_length_select(self):
        # N white LEDs from the home end (= playfield start), N = _select_length.
        if self._pf_len <= 0:
            return
        n = self._select_length
        if n > self._pf_len:
            n = self._pf_len
        for k in range(n):
            self.led.strip[self._pf_start + k] = (LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX, LED_BRIGHTNESS_MAX)

    def _render_rows(self, secret_revealed):
        """Render history rows (newest at home end). On reveal, prepend the
        secret as the newest row before rendering history.

        Layout per §6.3: a single row is `%xxxx%yyyy%` = L guess + 1 mid
        separator + L feedback + 1 trailing separator = 2L + 2 LEDs. The
        leading separator at the home end is shared with the strip's
        boundary, so it's counted once outside the per-row loop. With pf_len
        LEDs, rows_visible = (pf_len - 1) // (2L + 2)."""
        if self._pf_len <= 0:
            return
        L = self._length
        per_row = 2 * L + 2

        # Build the list of rows to render, newest first. On reveal, prepend
        # the secret as the "newest" row so it sits at the home end.
        rows_to_draw = []
        if secret_revealed:
            rows_to_draw.append({"guess": list(self._secret), "greens": 0, "reds": 0, "is_secret": True})
        for h in self._history:
            rows_to_draw.append({"guess": h["guess"], "greens": h["greens"], "reds": h["reds"], "is_secret": False})

        # Leading separator at home end always lit while the game is in progress.
        idx = self._pf_start
        self.led.strip[idx] = COLOR_SEPARATOR
        idx += 1

        rows_visible = (self._pf_len - 1) // per_row
        if rows_visible <= 0:
            return
        rows_to_draw = rows_to_draw[:rows_visible]
        for row in rows_to_draw:
            # L guess slots
            for c in row["guess"]:
                if idx > self._pf_end:
                    return
                self.led.strip[idx] = _COLOR_MAP.get(c, COLOR_BLACK)
                idx += 1
            # mid separator
            if idx > self._pf_end:
                return
            self.led.strip[idx] = COLOR_SEPARATOR
            idx += 1
            # feedback slots: greens first (closest to leading sep), then reds,
            # then dark for unused. Skip on the revealed-secret row.
            if row.get("is_secret"):
                # Skip feedback slots for the revealed secret row (per §6.8).
                idx += L
            else:
                greens = row["greens"]
                reds = row["reds"]
                for k in range(L):
                    if idx > self._pf_end:
                        return
                    if k < greens:
                        self.led.strip[idx] = (0, LED_BRIGHTNESS_MAX, 0)
                    elif k < greens + reds:
                        self.led.strip[idx] = (LED_BRIGHTNESS_MAX, 0, 0)
                    else:
                        self.led.strip[idx] = COLOR_BLACK
                    idx += 1
            # trailing separator
            if idx > self._pf_end:
                return
            self.led.strip[idx] = COLOR_SEPARATOR
            idx += 1
