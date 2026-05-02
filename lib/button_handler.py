# Button handler with debouncing, hold detection, and alternating adjustments

import machine
import time
from config import (
    PIN_BUTTON_OFF,
    PIN_BUTTON_AUTO,
    PIN_BUTTON_ON,
    PIN_BUTTON_F1,
    PIN_BUTTON_F2,
    PIN_BUTTON_ALT,
    PIN_BUTTON_R,
    PIN_BUTTON_G,
    PIN_BUTTON_B,
    BUTTON_DEBOUNCE_MS,
    BUTTON_HOLD_MS,
    BUTTON_COMBO_MS,
    BUTTON_MIX_WINDOW_MS,
    BRIGHTNESS_STEP,
    HUE_STEP,
    SATURATION_STEP
)


_MIX_OF = {
    ("R", "G"): "Y", ("G", "R"): "Y",
    ("G", "B"): "C", ("B", "G"): "C",
    ("R", "B"): "M", ("B", "R"): "M",
}

# All physical buttons we track. Order is the iteration order in update().
_BTN_NAMES = ("off", "auto", "on", "f1", "f2", "alt")


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

        # Game-mode input: while True, row-1 short presses fire game balls,
        # row-2 (F1/F2/ALT) drives game-control actions.
        self.game_input_mode = False

        # Per-button-name -> game shoot color, resolved from pin numbers so the
        # user can re-map pins without changing this mapping.
        self._game_color_by_btn = {}
        for btn_name, pin in (("off", PIN_BUTTON_OFF), ("auto", PIN_BUTTON_AUTO), ("on", PIN_BUTTON_ON)):
            if pin == PIN_BUTTON_R:
                self._game_color_by_btn[btn_name] = "R"
            elif pin == PIN_BUTTON_G:
                self._game_color_by_btn[btn_name] = "G"
            elif pin == PIN_BUTTON_B:
                self._game_color_by_btn[btn_name] = "B"

        # Per-game-color last-press timestamp (for mix-window detection).
        # 0 = not currently held.
        self._game_last_press = {"R": 0, "G": 0, "B": 0}

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
        for n in _BTN_NAMES:
            self.button_held[n] = False
            self.hold_start_time[n] = 0
        self.all_buttons_pressed = False
        self.combo_start_time = 0
        self._game_last_press["R"] = 0
        self._game_last_press["G"] = 0
        self._game_last_press["B"] = 0

    def update(self):
        """
        Update button states and dispatch button logic.
        Returns dict with actions (always all keys present):
          mode_change:    'off'|'on'|'auto'|None  (legacy log/handle hint)
          mode_temporary: bool|None               (only meaningful for off/on)
          ap_mode:        bool                    (3-combo, non-game only)
          abort_game:     bool                    (ALT+F1, game only)
          start_game:     bool                    (F1, non-game only)
          level_delta:    int                     (F1=+1 / F2=-1, game only,
                                                   honored only if no shots fired)
          shoot_colors:   list[str]               (R/G/B, game only)
          upgrade_mixes:  list[str]               (Y/C/M, game only)
        """
        actions = {
            'mode_change': None,
            'mode_temporary': None,
            'ap_mode': False,
            'abort_game': False,
            'start_game': False,
            'level_delta': 0,
            'shoot_colors': [],
            'upgrade_mixes': [],
        }

        # Console diagnostic: print held-button snapshot when it changes.
        # Uses raw pin reads (pre-debounce) so wiring/pin issues are visible.
        self._maybe_print_state()

        # 3-combo: AP mode only when not in game (in-game it's now a no-op).
        if self.check_ap_mode_combo():
            if not self.game_input_mode:
                actions['ap_mode'] = True
            return actions

        now = time.ticks_ms()
        current_mode = self.storage.get_mode()

        for btn_name in _BTN_NAMES:
            btn = self._btn_obj[btn_name]
            is_pressed = self._is_pressed(btn)

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
                        # Game-mode: row-1 buttons fire on press edge.
                        if self.game_input_mode and btn_name in ("off", "auto", "on"):
                            self._on_game_press_edge(btn_name, now, actions)
                else:
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    # Holds (brightness/hue/saturation) only:
                    #  - not in game mode
                    #  - row-1 buttons only (off/auto/on)
                    #  - current mode is "on"
                    if (not self.game_input_mode
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

                    # Clear game last-press timestamp on row-1 release (game mode).
                    if self.game_input_mode and btn_name in ("off", "auto", "on"):
                        color = self._game_color_by_btn.get(btn_name)
                        if color is not None:
                            self._game_last_press[color] = 0

        return actions

    # ---- Game-mode press-edge handler for row-1 (R/G/B) ----

    def _on_game_press_edge(self, btn_name, now, actions):
        color = self._game_color_by_btn.get(btn_name)
        if color is None:
            return
        actions['shoot_colors'].append(color)
        # Mix window: if another primary is held within window, queue upgrade.
        for other, other_ts in self._game_last_press.items():
            if other == color or other_ts == 0:
                continue
            if time.ticks_diff(now, other_ts) <= BUTTON_MIX_WINDOW_MS:
                mix = _MIX_OF.get((color, other))
                if mix:
                    actions['upgrade_mixes'].append(mix)
                break
        self._game_last_press[color] = now

    # ---- Short-release dispatcher (release-edge, after hold check) ----

    def _on_short_release(self, btn_name, actions):
        # In game mode, row-1 already fired on press edge: nothing on release.
        if self.game_input_mode and btn_name in ("off", "auto", "on"):
            return

        # ALT counts as a modifier if it was held at press time OR is still
        # held at release time. Order-independent chord.
        alt = self.alt_at_press.get(btn_name, False) or (
            (btn_name != "alt") and self._alt_held()
        )

        if btn_name == "off":
            # Bare = mode off + temporary; ALT = mode off + perma.
            self._set_mode_with_temporary("off", temporary=not alt)
            actions['mode_change'] = "off"
            actions['mode_temporary'] = (not alt)
        elif btn_name == "on":
            self._set_mode_with_temporary("on", temporary=not alt)
            actions['mode_change'] = "on"
            actions['mode_temporary'] = (not alt)
        elif btn_name == "auto":
            if alt:
                # ALT+AUTO -> rainbow (temporary).
                self._set_mode_with_temporary("rainbow", temporary=True)
                actions['mode_change'] = "rainbow"
                actions['mode_temporary'] = True
            else:
                # Bare AUTO -> auto/schedule mode.
                self.storage.set_mode("auto")
                actions['mode_change'] = "auto"
        elif btn_name == "f1":
            if self.game_input_mode:
                if alt:
                    actions['abort_game'] = True
                else:
                    actions['level_delta'] += 1
            else:
                # Outside game: F1 starts a game (ALT modifier currently ignored).
                actions['start_game'] = True
        elif btn_name == "f2":
            if self.game_input_mode and not alt:
                actions['level_delta'] -= 1
            # F2 outside game: no-op for now.
        elif btn_name == "alt":
            # ALT alone: no callback at this time (per user).
            pass

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
