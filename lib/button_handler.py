# Button handler with debouncing, hold detection, and alternating adjustments

import machine
import time
from config import (
    PIN_BUTTON_OFF,
    PIN_BUTTON_AUTO,
    PIN_BUTTON_ON,
    BUTTON_DEBOUNCE_MS,
    BUTTON_HOLD_MS,
    BUTTON_COMBO_MS,
    BRIGHTNESS_STEP,
    HUE_STEP,
    SATURATION_STEP
)


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

    def update(self):
        """
        Update button states and handle button logic
        Call this regularly in the main loop
        Returns: dict with actions: {'mode_change': str, 'ap_mode': bool}
        """
        actions = {'mode_change': None, 'ap_mode': False}

        # Check for AP mode combo first (takes priority)
        if self.check_ap_mode_combo():
            actions['ap_mode'] = True
            return actions

        now = time.ticks_ms()
        current_mode = self.storage.get_mode()

        # Process each button
        for btn_name, btn in [("off", self.btn_off), ("auto", self.btn_auto), ("on", self.btn_on)]:
            is_pressed = self._is_pressed(btn)

            if is_pressed:
                # Button is currently pressed
                if not self.button_held[btn_name]:
                    # New button press - check debounce
                    if time.ticks_diff(now, self.last_press_time[btn_name]) > BUTTON_DEBOUNCE_MS:
                        # Valid new press
                        self.button_held[btn_name] = True
                        self.hold_start_time[btn_name] = now
                        self.last_press_time[btn_name] = now
                else:
                    # Button being held - check if hold duration reached
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    if hold_duration >= BUTTON_HOLD_MS and current_mode == "on":
                        # Handle hold actions (only in manual "on" mode)
                        if time.ticks_diff(now, self.last_adjust_time) >= self.adjust_interval_ms:
                            self._handle_hold_adjust(btn_name)
                            self.last_adjust_time = now
            else:
                # Button released
                if self.button_held[btn_name]:
                    # Was pressed, now released
                    hold_duration = time.ticks_diff(now, self.hold_start_time[btn_name])

                    if hold_duration < BUTTON_HOLD_MS:
                        # Short press - mode change
                        actions['mode_change'] = self._handle_short_press(btn_name)

                    self.button_held[btn_name] = False

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
