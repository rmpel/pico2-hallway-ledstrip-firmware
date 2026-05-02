# HallwayLedBar - Main Program
# Pi Pico W LED strip controller with web interface and sunrise/sunset scheduling

import time
import machine
import _thread

# Import our modules
from lib.config import TRANSITION_UPDATE_MS
from lib.storage import Storage
from lib.led_controller import LEDController
from lib.button_handler import ButtonHandler
from lib.wifi_manager import WiFiManager
from lib.scheduler import Scheduler
from lib.sun_times import SunTimes
from lib.web_server import WebServer
from lib.ntp_sync import NTPSync
from lib.tz_offset import TzOffset
from lib.game import Game


class HallwayLedBar:
    def __init__(self):
        """Initialize the HallwayLedBar system"""
        print("=" * 50)
        print("HallwayLedBar Starting...")
        print("=" * 50)

        # Initialize components
        self.storage = Storage()
        self.led = LEDController()
        self.wifi = WiFiManager(self.storage, self.led)
        self.scheduler = Scheduler(self.storage, self.led)
        self.sun_times = SunTimes(self.storage)
        self.ntp = NTPSync(self.storage)
        self.tz_offset = TzOffset(self.storage)
        self.buttons = ButtonHandler(self.storage, self.led)
        self.game = Game(self.led, self.storage)
        self.game.on_active_change = lambda active: self.buttons.set_game_input_mode(active)
        self.web_server = WebServer(self.storage, self.wifi, self.scheduler, self.sun_times, self.ntp, self.tz_offset, self.game)

        # State
        self.last_transition_update = 0
        self.last_sun_times_update = 0
        self.last_ntp_sync = 0
        self.last_reboot_check = 0
        self.sun_times_update_interval = 3600000  # Update every hour
        self.ntp_sync_interval = 3600000  # Sync time every hour
        self.reboot_check_interval = 30000  # Check scheduled reboot every 30s
        self.web_server_running = False

        # Start up
        self._startup()

    def _startup(self):
        """Initial startup sequence"""
        # Turn off LEDs initially
        self.led.turn_off()

        # Ensure both WiFi interfaces are off before starting
        import time
        self.wifi.wlan_ap.active(False)
        self.wifi.wlan_sta.active(False)
        time.sleep(2)  # Give WiFi hardware time to reset

        # Try to connect to WiFi if configured
        if self.storage.has_wifi_config():
            print("WiFi credentials found, attempting connection...")
            if self.wifi.connect_to_wifi():
                print("WiFi connected successfully")
                self._start_normal_mode()
            else:
                print("WiFi connection failed, starting AP mode")
                self._start_ap_mode()
        else:
            print("No WiFi configured, starting AP mode")
            self._start_ap_mode()

    def _start_ap_mode(self):
        """Start Access Point mode for configuration"""
        ip = self.wifi.start_ap_mode()
        self.web_server.start()
        self._start_web_server_thread()
        print(f"AP Mode active - connect to WiFi and navigate to http://{ip}")

    def _start_normal_mode(self):
        """Start normal operation mode"""
        # Pre-set RTC to (reboot_time + 1 minute) UTC so the schedule has a
        # plausible time even before NTP completes. Also prevents a reboot
        # loop: the scheduled-reboot check sees we're already past the window.
        self._preset_rtc_from_reboot_time()

        # Sync time with NTP (UTC)
        print("Synchronizing time with NTP server...")
        if self.ntp.sync_time(force=True):
            print("Time synchronized successfully")
        else:
            print("Failed to sync time, will retry later")

        # Refresh tz offset from coords (cached weekly)
        if self.storage.has_location_config():
            self.tz_offset.refresh()

        # Fetch sun times
        if self.storage.has_location_config():
            print("Fetching sun times...")
            if self.sun_times.update_scheduler(self.scheduler):
                print("Sun times updated successfully")
            else:
                print("Failed to fetch sun times, will retry later")
        else:
            print("Location not configured, cannot fetch sun times")

        # Start web server
        self.web_server.start()
        self._start_web_server_thread()
        print("Normal mode active")

        # Keep green status LED on for 3 seconds, then turn off
        time.sleep(3)
        self.led.stop_status_led()
        print("Status LED turned off")

    def _start_web_server_thread(self):
        """Start web server on second CPU core"""
        if not self.web_server_running:
            print("Starting web server on core 1...")
            _thread.start_new_thread(self._web_server_loop, ())
            self.web_server_running = True

    def _web_server_loop(self):
        """Web server loop running on core 1"""
        print("Web server thread started on core 1")
        while True:
            try:
                self.web_server.handle_request()
                time.sleep_ms(1)  # Tight loop on dedicated core
            except Exception as e:
                print(f"Web server error: {e}")

    def _update_mode(self):
        """Update LED state based on current mode"""
        if self.web_server and getattr(self.web_server, "preview_active", False):
            return
        # Pump the game every cycle. When inactive it just drains pending inputs
        # so a queued start request transitions state in the same loop iteration.
        self.game.tick()
        if self.game.is_active():
            return
        mode = self.storage.get_mode()

        # Auto-resume: in non-auto mode, if the schedule step rolls over
        # (and the user opted into temporary mode), switch back to auto.
        if mode != "auto":
            if self.storage.get_non_auto_is_temporary():
                if self.scheduler._step_baseline is None:
                    self.scheduler.prime_step_baseline()
                elif self.scheduler.step_changed_since_baseline():
                    print("Schedule step changed; resuming auto mode")
                    self.storage.set_mode("auto")
                    self.scheduler._step_baseline = None
                    mode = "auto"
            else:
                # Flag off -> ensure baseline is cleared so a later toggle starts fresh.
                self.scheduler._step_baseline = None
        else:
            # In auto mode, no baseline needed.
            self.scheduler._step_baseline = None

        if mode == "off":
            # Turn off LEDs
            self.led.turn_off()

        elif mode == "on":
            # Manual mode - use stored manual settings
            brightness, hue, saturation = self.storage.get_manual_settings()
            self.led.set_color_hsv(hue, saturation, brightness)

        elif mode == "rainbow":
            # Rainbow mode - animated rainbow across all LEDs
            brightness, _, saturation = self.storage.get_manual_settings()
            self.led.update_rainbow(saturation, brightness)

        elif mode == "auto":
            # Auto mode - use scheduler
            self.scheduler.update()

    def _check_ntp_sync(self):
        """Periodically sync time with NTP"""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_ntp_sync) >= self.ntp_sync_interval:
            if self.wifi.ensure_connected():
                print("Syncing time with NTP...")
                self.ntp.sync_time()
            self.last_ntp_sync = now

    def _check_sun_times_update(self):
        """Periodically update sun times and tz offset (tz_offset self-throttles weekly)"""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_sun_times_update) >= self.sun_times_update_interval:
            if self.storage.has_location_config() and self.wifi.ensure_connected():
                print("Updating sun times...")
                self.sun_times.update_scheduler(self.scheduler)
                self.tz_offset.refresh()
            self.last_sun_times_update = now

    def _parse_hhmm(self, s):
        """Parse 'HH:MM' -> (hour, minute) or None."""
        if not s or ":" not in s:
            return None
        try:
            h, m = s.split(":", 1)
            h = int(h)
            m = int(m)
            if 0 <= h < 24 and 0 <= m < 60:
                return (h, m)
        except ValueError:
            pass
        return None

    def _preset_rtc_from_reboot_time(self):
        """
        On boot, set the RTC to (reboot_time + 1 minute) in UTC, using the
        current RTC's date as the date. This gives the schedule a sensible
        time before NTP arrives, and prevents an immediate re-trigger of
        the scheduled reboot since current time is already past it.
        """
        hhmm = self.storage.get_reboot_time()
        parsed = self._parse_hhmm(hhmm)
        if parsed is None:
            return
        local_h, local_m = parsed
        tz_offset = self.storage.get_tz_offset_seconds()
        # Reboot time is local; convert to UTC seconds-since-midnight, add 60s.
        local_secs = local_h * 3600 + local_m * 60
        utc_secs = (local_secs - tz_offset + 60) % 86400
        utc_h = utc_secs // 3600
        utc_m = (utc_secs % 3600) // 60
        utc_s = utc_secs % 60
        rtc = machine.RTC()
        # Keep current date; only override H/M/S. weekday=0 is fine, NTP fixes it.
        now = rtc.datetime()
        # MicroPython RTC tuple: (year, month, day, weekday, hour, minute, second, subsecond)
        rtc.datetime((now[0], now[1], now[2], now[3], utc_h, utc_m, utc_s, 0))
        print(f"Pre-set RTC to {utc_h:02d}:{utc_m:02d}:{utc_s:02d} UTC (reboot_time {hhmm} +1min)")

    def _check_scheduled_reboot(self):
        """If current local time is within a minute of reboot_time, reset."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_reboot_check) < self.reboot_check_interval:
            return
        self.last_reboot_check = now
        hhmm = self.storage.get_reboot_time()
        parsed = self._parse_hhmm(hhmm)
        if parsed is None:
            return
        target_h, target_m = parsed
        target_secs = target_h * 3600 + target_m * 60
        # Use scheduler's local-seconds-since-midnight (UTC + tz_offset).
        local_secs = self.scheduler._get_current_time_seconds()
        delta = local_secs - target_secs
        # Trigger inside [0, 60) seconds past target.
        if 0 <= delta < 60:
            print(f"Scheduled reboot triggered at local {local_secs}s (target {target_secs}s)")
            time.sleep(1)
            machine.reset()

    def run(self):
        """Main loop"""
        print("Entering main loop...")

        while True:
            try:
                # Handle button inputs
                button_actions = self.buttons.update()

                if self.game.is_active():
                    # In-game: physical buttons drive game inputs only.
                    if button_actions['abort_game']:
                        print("Game aborted by button combo")
                        self.game.stop()
                    else:
                        for c in button_actions.get('shoot_colors', ()):
                            self.game.shoot(c)
                        for m in button_actions.get('upgrade_mixes', ()):
                            self.game.upgrade_last_ball(m)
                else:
                    # Check for AP mode trigger
                    if button_actions['ap_mode']:
                        print("AP mode triggered by button combo")
                        self.web_server.stop()
                        self._start_ap_mode()
                        continue

                    # Handle mode changes from buttons
                    if button_actions['mode_change']:
                        print(f"Mode changed to: {button_actions['mode_change']}")

                # Update status LED flash if active
                self.led.update_status_led_flash()

                # Update LED state based on mode
                self._update_mode()

                # Periodic tasks (only in normal mode)
                if not self.wifi.is_ap_mode:
                    self._check_ntp_sync()
                    self._check_sun_times_update()
                    self._check_scheduled_reboot()

                # Small yield to allow REPL access
                # Note: Web server runs on core 1, so we don't handle it here
                time.sleep_ms(10)

            except Exception as e:
                print(f"Error in main loop: {e}")
                import sys
                sys.print_exception(e)
                time.sleep(1)


# Entry point
if __name__ == "__main__":
    try:
        app = HallwayLedBar()
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        import sys
        sys.print_exception(e)
        # Blink red to indicate error
        led = LEDController()
        for _ in range(10):
            led.flash_red()
            time.sleep(1)
