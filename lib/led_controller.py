# LED Controller with HSV support for WS2812 strips

import machine
import neopixel
import time
from config import PIN_LED_STRIP, NUM_LEDS, LED_START_OFFSET, LED_BRIGHTNESS_MAX


class LEDController:
    def __init__(self):
        """Initialize the WS2812 LED strip controller"""
        try:
            self.pin = machine.Pin(PIN_LED_STRIP)
            self.strip = neopixel.NeoPixel(self.pin, NUM_LEDS)
            self.enabled = True
            print(f"LED strip initialized on pin {PIN_LED_STRIP}")
        except Exception as e:
            print(f"LED strip init failed (this is OK if not connected): {e}")
            self.strip = None
            self.enabled = False

        self.current_hsv = (0, 0, 0)  # (hue, saturation, brightness)
        self.target_hsv = (0, 0, 0)
        self.transition_start_time = None
        self.transition_duration = 0

        # Rainbow mode state
        self.rainbow_offset = 0
        self.rainbow_last_update = 0
        self.rainbow_update_interval = 0  # Update every call (no throttling)
        self.rainbow_step_size = 3  # Degrees to shift per update
        # Actual measured loop time is ~150ms, so: 360°/3° = 120 steps × 150ms = ~18 seconds per cycle

        # Status LED state (LED 0)
        self.status_led_active = False
        self.status_led_flash_state = False
        self.status_led_last_flash = 0
        self.status_led_color = (0, 0, 0)

    def hsv_to_rgb(self, h, s, v):
        """
        Convert HSV to RGB
        h: 0-360 (degrees)
        s: 0-100 (percent)
        v: 0-100 (percent)
        Returns: (r, g, b) tuple with values 0-255
        """
        # Normalize inputs
        h = h % 360
        s = max(0, min(100, s)) / 100.0
        v = max(0, min(100, v)) / 100.0

        # Treat sub-1% brightness as fully off (avoids float-noise glow,
        # and lets a scheduled 0% step actually go dark).
        if v < 0.01:
            return (0, 0, 0)

        if s == 0:
            # Grayscale
            val = int(v * LED_BRIGHTNESS_MAX)
            return (val, val, val)

        # Calculate RGB
        h_i = int(h / 60.0) % 6
        f = (h / 60.0) - h_i
        p = v * (1.0 - s)
        q = v * (1.0 - f * s)
        t = v * (1.0 - (1.0 - f) * s)

        if h_i == 0:
            r, g, b = v, t, p
        elif h_i == 1:
            r, g, b = q, v, p
        elif h_i == 2:
            r, g, b = p, v, t
        elif h_i == 3:
            r, g, b = p, q, v
        elif h_i == 4:
            r, g, b = t, p, v
        else:
            r, g, b = v, p, q

        return (
            int(r * LED_BRIGHTNESS_MAX),
            int(g * LED_BRIGHTNESS_MAX),
            int(b * LED_BRIGHTNESS_MAX)
        )

    def set_color_hsv(self, hue, saturation, brightness):
        """
        Set all LEDs to a specific HSV color immediately
        hue: 0-360
        saturation: 0-100
        brightness: 0-100
        """
        self.current_hsv = (hue, saturation, brightness)
        self.target_hsv = (hue, saturation, brightness)

        if not self.enabled:
            return

        rgb = self.hsv_to_rgb(hue, saturation, brightness)

        # Set all LEDs to black first
        for i in range(NUM_LEDS):
            self.strip[i] = (0, 0, 0)

        # Only light up LEDs starting from offset
        for i in range(LED_START_OFFSET, NUM_LEDS):
            self.strip[i] = rgb
        self.strip.write()

    def start_transition(self, target_hue, target_sat, target_bright, duration_ms):
        """
        Start a smooth transition to target HSV values
        duration_ms: transition time in milliseconds
        """
        self.target_hsv = (target_hue, target_sat, target_bright)
        self.transition_start_time = time.ticks_ms()
        self.transition_duration = duration_ms

    def update_transition(self):
        """
        Update the current color during a transition
        Call this regularly in the main loop
        Returns: True if transition is complete, False otherwise
        """
        if self.transition_start_time is None:
            return True

        if not self.enabled:
            return True

        elapsed = time.ticks_diff(time.ticks_ms(), self.transition_start_time)

        if elapsed >= self.transition_duration:
            # Transition complete
            self.current_hsv = self.target_hsv
            self.transition_start_time = None
            self.set_color_hsv(*self.current_hsv)
            return True

        # Calculate interpolated values
        progress = elapsed / self.transition_duration

        h_start, s_start, v_start = self.current_hsv
        h_target, s_target, v_target = self.target_hsv

        # Interpolate hue (handle wraparound)
        h_diff = h_target - h_start
        if abs(h_diff) > 180:
            if h_diff > 0:
                h_diff -= 360
            else:
                h_diff += 360
        h_current = (h_start + h_diff * progress) % 360

        # Linear interpolation for saturation and brightness
        s_current = s_start + (s_target - s_start) * progress
        v_current = v_start + (v_target - v_start) * progress

        # Update LEDs
        rgb = self.hsv_to_rgb(h_current, s_current, v_current)

        # Set all LEDs to black first
        for i in range(NUM_LEDS):
            self.strip[i] = (0, 0, 0)

        # Only light up LEDs starting from offset
        for i in range(LED_START_OFFSET, NUM_LEDS):
            self.strip[i] = rgb
        self.strip.write()

        return False

    def flash(self, hue, saturation, brightness, duration_ms=500, count=3):
        """
        Flash the LED strip (for visual feedback)
        """
        original_hsv = self.current_hsv

        for _ in range(count):
            self.set_color_hsv(hue, saturation, brightness)
            time.sleep_ms(duration_ms)
            self.set_color_hsv(0, 0, 0)
            time.sleep_ms(duration_ms)

        # Restore original color
        self.set_color_hsv(*original_hsv)

    def flash_red(self):
        """Flash red (error/failure)"""
        self.flash(0, 100, 50, duration_ms=300, count=3)

    def flash_green(self):
        """Flash green (success)"""
        self.flash(120, 100, 50, duration_ms=300, count=3)

    def flash_white(self):
        """Flash white (entering AP mode)"""
        self.flash(0, 0, 100, duration_ms=200, count=5)

    def turn_off(self):
        """Turn off all LEDs"""
        self.set_color_hsv(0, 0, 0)

    def get_current_hsv(self):
        """Get current HSV values"""
        return self.current_hsv

    def update_rainbow(self, saturation=100, brightness=50):
        """
        Update rainbow animation
        Spreads full 360° hue spectrum across all LEDs and animates
        Call this regularly (e.g., every 100ms) to animate the rainbow

        saturation: 0-100
        brightness: 0-100
        """
        if not self.enabled:
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self.rainbow_last_update) < self.rainbow_update_interval:
            return

        # Calculate hue for each LED
        active_leds = NUM_LEDS - LED_START_OFFSET

        for i in range(NUM_LEDS):
            if i < LED_START_OFFSET:
                # Turn off LEDs before offset
                self.strip[i] = (0, 0, 0)
            else:
                # Calculate hue based on LED position and animation offset
                led_index = i - LED_START_OFFSET
                # Spread 360 degrees across all active LEDs
                base_hue = (led_index * 360.0 / active_leds) if active_leds > 0 else 0
                # Add animation offset
                hue = (base_hue + self.rainbow_offset) % 360
                # Convert to RGB and set
                rgb = self.hsv_to_rgb(hue, saturation, brightness)
                self.strip[i] = rgb

        self.strip.write()

        # Increment offset for animation
        self.rainbow_offset = (self.rainbow_offset + self.rainbow_step_size) % 360
        self.rainbow_last_update = now

    def set_status_led(self, color_rgb):
        """
        Set status LED (LED 0) to a specific RGB color
        color_rgb: (r, g, b) tuple with values 0-255
        """
        if not self.enabled:
            return

        self.status_led_color = color_rgb
        self.status_led_active = True
        self.strip[0] = color_rgb
        self.strip.write()

    def start_status_led_flash(self, color_rgb):
        """
        Start flashing status LED (LED 0)
        color_rgb: (r, g, b) tuple with values 0-255
        """
        self.status_led_active = True
        self.status_led_color = color_rgb
        self.status_led_flash_state = True
        self.status_led_last_flash = time.ticks_ms()

    def update_status_led_flash(self):
        """
        Update status LED flash state
        Call this regularly in the main loop
        """
        if not self.enabled or not self.status_led_active:
            return

        now = time.ticks_ms()
        if time.ticks_diff(now, self.status_led_last_flash) >= 500:  # Flash every 500ms
            self.status_led_flash_state = not self.status_led_flash_state
            self.status_led_last_flash = now

            if self.status_led_flash_state:
                self.strip[0] = self.status_led_color
            else:
                self.strip[0] = (0, 0, 0)
            self.strip.write()

    def stop_status_led(self):
        """Turn off status LED"""
        if not self.enabled:
            return

        self.status_led_active = False
        self.status_led_flash_state = False
        self.strip[0] = (0, 0, 0)
        self.strip.write()

    def status_led_connecting(self):
        """Flash orange while connecting to WiFi"""
        self.start_status_led_flash((255, 165, 0))  # Orange

    def status_led_failed(self):
        """Show red for WiFi connection failure"""
        self.set_status_led((255, 0, 0))  # Red

    def status_led_success(self):
        """Show green for WiFi connection success"""
        self.set_status_led((0, 255, 0))  # Green
