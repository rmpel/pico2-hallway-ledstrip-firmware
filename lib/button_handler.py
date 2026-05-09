# Button handler with debouncing, hold detection, and alternating adjustments

import json
import machine
import time
from config import (
    PIN_BUTTON_OFF,
    PIN_BUTTON_AUTO,
    PIN_BUTTON_ON,
    PIN_BUTTON_F1,
    PIN_BUTTON_F2,
    PIN_BUTTON_ALT,
    BUTTON_DEBOUNCE_MS,
    BUTTON_HOLD_MS,
    BUTTON_COMBO_MS,
    BRIGHTNESS_STEP,
    HUE_STEP,
    SATURATION_STEP
)


# All physical buttons we track. Order is the iteration order in update().
_BTN_NAMES = ("off", "auto", "on", "f1", "f2", "alt")

# Universal abort: F1 held this long aborts a running game (or exits the
# game-select carousel). The threshold is independent of BUTTON_HOLD_MS so it
# survives changes to manual-mode hold semantics.
_F1_HELD_ABORT_MS = 3000

# Snake's defaults: shoot_red=off, shoot_green=auto, shoot_blue=on,
# shoot_yellow=f1, shoot_cyan=f2, shoot_magenta=alt. Each button maps to a
# color; the inverse (color->button) is what storage stores. We keep the
# button->color mapping here for press-edge resolution.
_DEFAULT_SNAKE_BUTTON_TO_COLOR = {
    "off":  "R",
    "auto": "G",
    "on":   "B",
    "f1":   "Y",
    "f2":   "C",
    "alt":  "M",
}
_SNAKE_ACTION_TO_COLOR = {
    "shoot_red":     "R",
    "shoot_green":   "G",
    "shoot_blue":    "B",
    "shoot_yellow":  "Y",
    "shoot_cyan":    "C",
    "shoot_magenta": "M",
}


def _load_snake_button_map():
    """Read /settings.json -> game.buttons and produce a button->color dict.
    Falls back to _DEFAULT_SNAKE_BUTTON_TO_COLOR for any missing or invalid
    entries. Read once at module import so this stays cheap on the hot path.
    """
    try:
        with open("/settings.json", "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return dict(_DEFAULT_SNAKE_BUTTON_TO_COLOR)
    g = data.get("game") if isinstance(data, dict) else None
    raw = g.get("buttons") if isinstance(g, dict) else None
    if not isinstance(raw, dict):
        return dict(_DEFAULT_SNAKE_BUTTON_TO_COLOR)
    # Start from defaults, overlay valid action->button entries.
    btn_to_color = dict(_DEFAULT_SNAKE_BUTTON_TO_COLOR)
    # The settings dict is action_name -> button_name. Invert for runtime use.
    # Track which buttons get reassigned so we don't end up with two actions
    # pointing at the same button (last-write-wins is fine; the user gets what
    # they configured).
    overlay = {}
    for action, btn in raw.items():
        color = _SNAKE_ACTION_TO_COLOR.get(action)
        if color is None or btn not in _BTN_NAMES:
            continue
        overlay[btn] = color
    btn_to_color.update(overlay)
    # If a button is unmapped after overlay (because the user moved its color
    # elsewhere and didn't replace it), drop it from the map so it's a no-op
    # in game mode rather than firing a stale color.
    used_colors = set(overlay.values())
    for btn in list(btn_to_color):
        if btn in overlay:
            continue
        if btn_to_color[btn] in used_colors:
            del btn_to_color[btn]
    return btn_to_color


class ButtonHandler:
    def __init__(self, storage, led_controller):
        """Initialize button handler"""
        self.storage = storage
        self.led = led_controller

        # Initialize buttons with pull-up resistors
        self.btn_off = machine.Pin(PIN_BUTTON_OFF, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_auto = machine.Pin(PIN_BUTTON_AUTO, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_on = machine.Pin(PIN_BUTTON_ON, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_f1 = machine.Pin(PIN_BUTTON_F1, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_f2 = machine.Pin(PIN_BUTTON_F2, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_alt = machine.Pin(PIN_BUTTON_ALT, machine.Pin.IN, machine.Pin.PULL_UP)

        self._btn_obj = {
            "off": self.btn_off, "auto": self.btn_auto, "on": self.btn_on,
            "f1": self.btn_f1, "f2": self.btn_f2, "alt": self.btn_alt,
        }

        # Per-button state tracking
        self.last_press_time = {n: 0 for n in _BTN_NAMES}
        self.button_held = {n: False for n in _BTN_NAMES}
        self.hold_start_time = {n: 0 for n in _BTN_NAMES}
        # ALT state captured at the press edge of each button (used so
        # modifier-decisions don't depend on release-order).
        self.alt_at_press = {n: False for n in _BTN_NAMES}
        # True if the current hold has actually triggered a hold-adjust at
        # least once — used to flip direction on release.
        self.did_hold_adjust = {n: False for n in _BTN_NAMES}
        # When game-input mode flips while a button is still physically held,
        # we mark it here so that the lingering press isn't reinterpreted as a
        # fresh press in the new mode (otherwise releasing F1 right after an
        # ALT+F1 abort would trigger start_game again, etc.). Cleared when the
        # button is observed released.
        self.ignore_until_release = {n: False for n in _BTN_NAMES}
        # F1-held-3s emits exactly once per press; cleared on release.
        self._f1_abort_emitted = False

        # Alternating adjustment direction (manual-mode hold semantics on row 1)
        self.brightness_increasing = True
        self.hue_rotating_right = True
        self.saturation_increasing = True

        # AP-mode combo detection (3-button hold on row 1: off+auto+on)
        self.all_buttons_pressed = False
        self.combo_start_time = 0

        # Adjustment timing
        self.last_adjust_time = 0
        self.adjust_interval_ms = 100  # Adjust every 100ms while holding

        # Game-mode input: while True, every button press fires a game color
        # via _game_color_by_btn. F1/F2 also drive level-delta and ALT+F1 still
        # aborts (legacy behavior preserved).
        self.game_input_mode = False

        # Game-select carousel input: while True, F1/F2 short releases are
        # signalled to main.py for carousel cycling/start, and the F1-held-3s
        # signal exits the carousel (vs aborting a game).
        self.game_select_input_mode = False

        # Active button -> color mapping for the running game. Defaults to
        # Snake's mapping (loaded from /settings.json -> game.buttons). Other
        # games override via set_active_color_map() when they become active.
        self._snake_color_map = _load_snake_button_map()
        self._active_color_map = dict(self._snake_color_map)

        # Last logged button-state snapshot (raw pin reads). Used to print a
        # status line only when something changes.
        self._last_state_print = None

    def _is_pressed(self, button):
        """Check if button is pressed (active low with pull-up)"""
        return button.value() == 0

    def _alt_held(self):
        return self._is_pressed(self.btn_alt)

    def check_ap_mode_combo(self):
        """
        Check if all 3 row-1 buttons are held for BUTTON_COMBO_MS (AP mode).
        """
        all_pressed = (
            self._is_pressed(self.btn_off) and
            self._is_pressed(self.btn_auto) and
            self._is_pressed(self.btn_on)
        )

        if all_pressed:
            if not self.all_buttons_pressed:
                self.all_buttons_pressed = True
                self.combo_start_time = time.ticks_ms()
            else:
                elapsed = time.ticks_diff(time.ticks_ms(), self.combo_start_time)
                if elapsed >= BUTTON_COMBO_MS:
                    self.all_buttons_pressed = False  # Reset
                    return True
        else:
            self.all_buttons_pressed = False

        return False

    def _maybe_print_state(self):
        """Print a single-line button snapshot whenever it changes.
        Pressed button shown as [NAME], released as -name-. Raw pin reads."""
        snap = tuple(self._is_pressed(self._btn_obj[n]) for n in _BTN_NAMES)
        if snap == self._last_state_print:
            return
        self._last_state_print = snap
        parts = []
        for name, pressed in zip(_BTN_NAMES, snap):
            if pressed:
                parts.append("[" + name.upper() + "]")
            else:
                parts.append("-" + name + "-")
        print("BTN " + " ".join(parts))

    def set_game_input_mode(self, flag):
        """Toggle game input mode. Clears stale press state so a press that
        spans the toggle doesn't bleed across modes."""
        self.game_input_mode = bool(flag)
        self._reset_press_state_for_mode_change()

    def set_game_select_input_mode(self, flag):
        """Toggle game-select-carousel input mode. Same press-state reset as
        a game-mode toggle so a held button doesn't bleed across modes."""
        self.game_select_input_mode = bool(flag)
        self._reset_press_state_for_mode_change()

    def set_active_color_map(self, color_map):
        """Switch the active button->color mapping. Pass None to revert to
        Snake's defaults. Called by main.py whenever a different game takes
        over the strip so each game can choose its own button assignments."""
        if color_map is None:
            self._active_color_map = dict(self._snake_color_map)
        else:
            self._active_color_map = dict(color_map)

    def _reset_press_state_for_mode_change(self):
        for n in _BTN_NAMES:
            # If the button is still physically held, don't let it count as a
            # fresh press in the new mode.
            if self._is_pressed(self._btn_obj[n]):
                self.ignore_until_release[n] = True
            self.button_held[n] = False
            self.hold_start_time[n] = 0
        self._f1_abort_emitted = False
        self.all_buttons_pressed = False
        self.combo_start_time = 0

    def update(self):
        """
        Update button states and dispatch button logic.
        Returns dict (always all keys present):
          mode_change:        'off'|'on'|'auto'|'rainbow'|None  (lighting only)
          mode_temporary:     bool|None
          ap_mode:            bool                              (3-combo, lighting only)
          abort_game:         bool                              (ALT+F1 in game OR F1-held-3s in game)
          start_game:         bool                              (legacy alias for f1_short_press in lighting)
          level_delta:        int                               (game-mode F1/F2 pre-shot)
          shoot_colors:       list[str]                         (game-mode press-edge colors)
          pressed_buttons:    list[str]                         (game-mode press-edge button names)
          f1_short_press:     bool                              (lighting OR carousel)
          f2_short_press:     bool                              (lighting OR carousel)
          f1_held_3s:         bool                              (any mode; once per press)
        """
        actions = {
            'mode_change': None,
            'mode_temporary': None,
            'ap_mode': False,
            'abort_game': False,
            'start_game': False,
            'level_delta': 0,
            'shoot_colors': [],
            'pressed_buttons': [],
            'f1_short_press': False,
            'f2_short_press': False,
            'f1_held_3s': False,
        }

        # Console diagnostic: print held-button snapshot when it changes.
        # Uses raw pin reads (pre-debounce) so wiring/pin issues are visible.
        self._maybe_print_state()

        # 3-combo: AP mode only when not in game/carousel.
        if self.check_ap_mode_combo():
            if not self.game_input_mode and not self.game_select_input_mode:
                actions['ap_mode'] = True
            return actions

        now = time.ticks_ms()
        current_mode = self.storage.get_mode()

        for btn_name in _BTN_NAMES:
            btn = self._btn_obj[btn_name]
            is_pressed = self._is_pressed(btn)

            # If the button was held during a mode toggle, ignore it entirely
            # until the user lifts it (then a fresh press is allowed).
            if self.ignore_until_release[btn_name]:
                if not is_pressed:
                    self.ignore_until_release[btn_name] = False
                    if btn_name == "f1":
                        self._f1_abort_emitted = False
                continue

            if is_pressed:
                if not self.button_held[btn_name]:
                    # Rising edge — debounce gate.
                    if time.ticks_diff(now, self.last_press_time[btn_name]) > BUTTON_DEBOUNCE_MS:
                        self.button_held[btn_name] = True
                        self.hold_start_time[btn_name] = now
                        self.last_press_time[btn_name] = now
                        # Capture ALT at press time so the modifier decision
                        # doesn't depend on release order.
                        self.alt_at_press[btn_name] = (btn_name != "alt") and self._alt_held()
                        self.did_hold_adjust[btn_name] = False
                        # Visual feedback: brief blip on the status LED so the
                        # user can confirm the button registered.
                        self.led.pulse_status_led((40, 40, 80), 30)
                        # Game-mode: every button fires its color on press edge.
                        if self.game_input_mode:
                            self._on_game_press_edge(btn_name, now, actions)
                else:
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    # F1-held-3s universal abort signal. Emitted exactly once
                    # per press; consumers (game / carousel / nothing) decide
                    # what to do. In lighting mode with no carousel open, the
                    # short-release start-game path is suppressed (see
                    # _on_short_release).
                    if (btn_name == "f1"
                            and not self._f1_abort_emitted
                            and hold_duration >= _F1_HELD_ABORT_MS):
                        self._f1_abort_emitted = True
                        actions['f1_held_3s'] = True
                        if self.game_input_mode:
                            actions['abort_game'] = True

                    # Holds (brightness/hue/saturation) only:
                    #  - not in game / carousel mode
                    #  - row-1 buttons only (off/auto/on)
                    #  - current mode is "on"
                    if (not self.game_input_mode
                            and not self.game_select_input_mode
                            and btn_name in ("off", "auto", "on")
                            and hold_duration >= BUTTON_HOLD_MS
                            and current_mode == "on"):
                        if time.ticks_diff(now, self.last_adjust_time) >= self.adjust_interval_ms:
                            self._handle_hold_adjust(btn_name)
                            self.last_adjust_time = now
                            self.did_hold_adjust[btn_name] = True
            else:
                if self.button_held[btn_name]:
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    if hold_duration < BUTTON_HOLD_MS:
                        self._on_short_release(btn_name, actions)
                    elif self.did_hold_adjust[btn_name]:
                        # Hold finished without flipping mid-hold; flip the
                        # adjustment direction so the next hold reverses.
                        self._flip_hold_direction(btn_name)

                    self.button_held[btn_name] = False
                    self.did_hold_adjust[btn_name] = False
                    if btn_name == "f1":
                        self._f1_abort_emitted = False

        return actions

    # ---- Game-mode press-edge handler (all 6 buttons fire a color) ----

    def _on_game_press_edge(self, btn_name, now, actions):
        # Each button fires its mapped color on press edge, using whichever
        # game's color map is currently active (set by main.py via
        # set_active_color_map). Buttons not present in the active map become
        # no-ops on the color path.
        actions['pressed_buttons'].append(btn_name)
        color = self._active_color_map.get(btn_name)
        if color is not None:
            actions['shoot_colors'].append(color)
        # Snake-specific pre-shot/abort signals. These are emitted unconditionally
        # in game mode; main.py is responsible for ignoring them when a game
        # other than Snake is active. (Universal F1-held-3s abort is still
        # emitted independently via update().)
        if btn_name == "f1":
            if self.alt_at_press.get("f1", False) or self._alt_held():
                actions['abort_game'] = True
            else:
                actions['level_delta'] += 1
        elif btn_name == "f2":
            actions['level_delta'] -= 1

    # ---- Short-release dispatcher (release-edge, after hold check) ----

    def _on_short_release(self, btn_name, actions):
        # Game mode: every button fires on press edge already. Releases do
        # nothing (apart from the F1-held-3s logic, handled in update()).
        if self.game_input_mode:
            return

        # Carousel mode: only F1/F2 releases matter — they cycle / start.
        # Other buttons are no-ops (and F1-held-3s exit is handled in update()).
        if self.game_select_input_mode:
            if btn_name == "f1":
                actions['f1_short_press'] = True
            elif btn_name == "f2":
                actions['f2_short_press'] = True
            return

        # ALT counts as a modifier if it was held at press time OR is still
        # held at release time. Order-independent chord.
        alt = self.alt_at_press.get(btn_name, False) or (
            (btn_name != "alt") and self._alt_held()
        )

        if btn_name == "off":
            self._set_mode_with_temporary("off", temporary=not alt)
            actions['mode_change'] = "off"
            actions['mode_temporary'] = (not alt)
        elif btn_name == "on":
            self._set_mode_with_temporary("on", temporary=not alt)
            actions['mode_change'] = "on"
            actions['mode_temporary'] = (not alt)
        elif btn_name == "auto":
            if alt:
                self._set_mode_with_temporary("rainbow", temporary=True)
                actions['mode_change'] = "rainbow"
                actions['mode_temporary'] = True
            else:
                self.storage.set_mode("auto")
                actions['mode_change'] = "auto"
        elif btn_name == "f1":
            # F1 short release in lighting mode: open game-select carousel.
            actions['f1_short_press'] = True
            # Legacy alias kept so existing callers (and test code) still see
            # start_game on the first F1 — main.py treats this as "open
            # carousel" now, not "start Snake".
            actions['start_game'] = True
        elif btn_name == "f2":
            # F2 short release in lighting mode: quick-start last game.
            actions['f2_short_press'] = True
        # ALT outside game/carousel: no-op.

    def _set_mode_with_temporary(self, mode, temporary):
        """Set mode (off/on) and the 'resume schedule at next event' flag in
        a single logical step."""
        self.storage.set_non_auto_is_temporary(bool(temporary))
        self.storage.set_mode(mode)

    def _handle_hold_adjust(self, button):
        """Handle hold adjustments in manual mode. Direction is locked for the
        duration of a single hold; releasing flips direction for next hold."""
        brightness, hue, saturation = self.storage.get_manual_settings()

        if button == "on":
            step = BRIGHTNESS_STEP if self.brightness_increasing else -BRIGHTNESS_STEP
            brightness = max(0, min(100, brightness + step))
            self.storage.set_manual_brightness(brightness)
            print(f"Brightness: {brightness}%")

        elif button == "off":
            step = HUE_STEP if self.hue_rotating_right else -HUE_STEP
            hue = (hue + step) % 360
            self.storage.set_manual_hue(hue)
            print(f"Hue: {hue}°")

        elif button == "auto":
            step = SATURATION_STEP if self.saturation_increasing else -SATURATION_STEP
            saturation = max(0, min(100, saturation + step))
            self.storage.set_manual_saturation(saturation)
            print(f"Saturation: {saturation}%")

        # Update LED immediately
        self.led.set_color_hsv(hue, saturation, brightness)

    def _flip_hold_direction(self, button):
        """Called once on release of a button that performed at least one
        hold-adjust step. Flips the direction so the next hold reverses."""
        if button == "on":
            self.brightness_increasing = not self.brightness_increasing
        elif button == "off":
            self.hue_rotating_right = not self.hue_rotating_right
        elif button == "auto":
            self.saturation_increasing = not self.saturation_increasing

    def reset_hold_state(self, button):
        """Reset hold state (used when releasing after hold)"""
        self.button_held[button] = False

    def toggle_brightness_direction(self):
        self.brightness_increasing = not self.brightness_increasing

    def toggle_hue_direction(self):
        self.hue_rotating_right = not self.hue_rotating_right

    def toggle_saturation_direction(self):
        self.saturation_increasing = not self.saturation_increasing
