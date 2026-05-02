# Button handler with debouncing, hold detection, and alternating adjustments

import machine
import time
from config import (
    PIN_BUTTON_OFF,
    PIN_BUTTON_AUTO,
    PIN_BUTTON_ON,
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


class ButtonHandler:
    def __init__(self, storage, led_controller):
        """Initialize button handler"""
        self.storage = storage
        self.led = led_controller

        # Initialize buttons with pull-up resistors
        self.btn_off = machine.Pin(PIN_BUTTON_OFF, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_auto = machine.Pin(PIN_BUTTON_AUTO, machine.Pin.IN, machine.Pin.PULL_UP)
        self.btn_on = machine.Pin(PIN_BUTTON_ON, machine.Pin.IN, machine.Pin.PULL_UP)

        # Button state tracking
        self.last_press_time = {"off": 0, "auto": 0, "on": 0}
        self.button_held = {"off": False, "auto": False, "on": False}
        self.hold_start_time = {"off": 0, "auto": 0, "on": 0}

        # Alternating adjustment direction
        self.brightness_increasing = True
        self.hue_rotating_right = True
        self.saturation_increasing = True

        # Combo detection
        self.all_buttons_pressed = False
        self.combo_start_time = 0

        # Adjustment timing
        self.last_adjust_time = 0
        self.adjust_interval_ms = 100  # Adjust every 100ms while holding

        # Game-mode input: while True, short presses fire game balls instead
        # of changing mode, and the all-3 combo aborts the game instead of
        # entering AP mode.
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

    def _is_pressed(self, button):
        """Check if button is pressed (active low with pull-up)"""
        return button.value() == 0

    def check_ap_mode_combo(self):
        """
        Check if all 3 buttons are held for 10 seconds (AP mode trigger)
        Returns: True if combo detected
        """
        all_pressed = (
            self._is_pressed(self.btn_off) and
            self._is_pressed(self.btn_auto) and
            self._is_pressed(self.btn_on)
        )

        if all_pressed:
            if not self.all_buttons_pressed:
                # Just started pressing all buttons
                self.all_buttons_pressed = True
                self.combo_start_time = time.ticks_ms()
            else:
                # Check if held long enough
                elapsed = time.ticks_diff(time.ticks_ms(), self.combo_start_time)
                if elapsed >= BUTTON_COMBO_MS:
                    self.all_buttons_pressed = False  # Reset
                    return True
        else:
            self.all_buttons_pressed = False

        return False

    def set_game_input_mode(self, flag):
        """Toggle game input mode. Clears stale press state so a press that
        spans the toggle doesn't bleed across modes."""
        self.game_input_mode = bool(flag)
        for btn_name in ("off", "auto", "on"):
            self.button_held[btn_name] = False
            self.hold_start_time[btn_name] = 0
        self.all_buttons_pressed = False
        self.combo_start_time = 0
        self._game_last_press["R"] = 0
        self._game_last_press["G"] = 0
        self._game_last_press["B"] = 0

    def update(self):
        """
        Update button states and handle button logic.
        Returns dict with actions:
          {'mode_change': str|None, 'ap_mode': bool, 'abort_game': bool,
           'shoot_colors': list[str],     # one or more of 'R'/'G'/'B'
           'upgrade_mixes': list[str]}    # one or more of 'Y'/'C'/'M'
        In non-game mode, shoot_colors / upgrade_mixes are always empty.
        In game mode, mode_change is always None.
        """
        actions = {
            'mode_change': None,
            'ap_mode': False,
            'abort_game': False,
            'shoot_colors': [],
            'upgrade_mixes': [],
        }

        # All-3 combo: AP mode normally, abort during game.
        if self.check_ap_mode_combo():
            if self.game_input_mode:
                actions['abort_game'] = True
            else:
                actions['ap_mode'] = True
            return actions

        now = time.ticks_ms()
        current_mode = self.storage.get_mode()

        # Process each button
        for btn_name, btn in [("off", self.btn_off), ("auto", self.btn_auto), ("on", self.btn_on)]:
            is_pressed = self._is_pressed(btn)

            if is_pressed:
                if not self.button_held[btn_name]:
                    # Rising edge — debounce gate.
                    if time.ticks_diff(now, self.last_press_time[btn_name]) > BUTTON_DEBOUNCE_MS:
                        self.button_held[btn_name] = True
                        self.hold_start_time[btn_name] = now
                        self.last_press_time[btn_name] = now

                        if self.game_input_mode:
                            color = self._game_color_by_btn.get(btn_name)
                            if color is not None:
                                actions['shoot_colors'].append(color)
                                # Mix window check: if another primary was
                                # pressed within BUTTON_MIX_WINDOW_MS, queue
                                # the mix-upgrade for the most recently
                                # launched ball.
                                for other, other_ts in self._game_last_press.items():
                                    if other == color or other_ts == 0:
                                        continue
                                    if time.ticks_diff(now, other_ts) <= BUTTON_MIX_WINDOW_MS:
                                        mix = _MIX_OF.get((color, other))
                                        if mix:
                                            actions['upgrade_mixes'].append(mix)
                                        break
                                self._game_last_press[color] = now
                else:
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    # Holds (brightness/hue/saturation) only when not in game input mode
                    if (not self.game_input_mode
                            and hold_duration >= BUTTON_HOLD_MS
                            and current_mode == "on"):
                        if time.ticks_diff(now, self.last_adjust_time) >= self.adjust_interval_ms:
                            self._handle_hold_adjust(btn_name)
                            self.last_adjust_time = now
            else:
                if self.button_held[btn_name]:
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    # Non-game mode keeps the original release-emit semantics for
                    # mode-change short presses. Game mode already fired on the
                    # press edge above, so release just clears state.
                    if (not self.game_input_mode) and hold_duration < BUTTON_HOLD_MS:
                        actions['mode_change'] = self._handle_short_press(btn_name)

                    self.button_held[btn_name] = False

                    # Clear game last-press timestamp on release.
                    if self.game_input_mode:
                        color = self._game_color_by_btn.get(btn_name)
                        if color is not None:
                            self._game_last_press[color] = 0

        return actions

    def _handle_short_press(self, button):
        """Handle short button press (mode change)"""
        if button == "off":
            self.storage.set_mode("off")
            return "off"
        elif button == "auto":
            self.storage.set_mode("auto")
            return "auto"
        elif button == "on":
            self.storage.set_mode("on")
            return "on"

    def _handle_hold_adjust(self, button):
        """Handle hold adjustments in manual mode"""
        brightness, hue, saturation = self.storage.get_manual_settings()

        if button == "on":
            # Adjust brightness
            if self.brightness_increasing:
                brightness = min(100, brightness + BRIGHTNESS_STEP)
                if brightness >= 100:
                    self.brightness_increasing = False  # Toggle for next hold
            else:
                brightness = max(0, brightness - BRIGHTNESS_STEP)
                if brightness <= 0:
                    self.brightness_increasing = True  # Toggle for next hold

            self.storage.set_manual_brightness(brightness)
            print(f"Brightness: {brightness}%")

        elif button == "off":
            # Adjust hue
            if self.hue_rotating_right:
                hue = (hue + HUE_STEP) % 360
            else:
                hue = (hue - HUE_STEP) % 360

            # Toggle direction when button is released and pressed again
            # (handled by alternating flag set on button release - see update logic)

            self.storage.set_manual_hue(hue)
            print(f"Hue: {hue}°")

        elif button == "auto":
            # Adjust saturation
            if self.saturation_increasing:
                saturation = min(100, saturation + SATURATION_STEP)
                if saturation >= 100:
                    self.saturation_increasing = False
            else:
                saturation = max(0, saturation - SATURATION_STEP)
                if saturation <= 0:
                    self.saturation_increasing = True

            self.storage.set_manual_saturation(saturation)
            print(f"Saturation: {saturation}%")

        # Update LED immediately
        self.led.set_color_hsv(hue, saturation, brightness)

    def reset_hold_state(self, button):
        """Reset hold state (used when releasing after hold)"""
        self.button_held[button] = False

    def toggle_brightness_direction(self):
        """Toggle brightness adjustment direction"""
        self.brightness_increasing = not self.brightness_increasing

    def toggle_hue_direction(self):
        """Toggle hue rotation direction"""
        self.hue_rotating_right = not self.hue_rotating_right

    def toggle_saturation_direction(self):
        """Toggle saturation adjustment direction"""
        self.saturation_increasing = not self.saturation_increasing
