# HallwayLedBar - Main Program
# Pi Pico W LED strip controller with web interface and sunrise/sunset scheduling

import gc
import time
import machine
import _thread

# Free anything left over from the boot sequence before we start importing
# our own modules — every byte of contiguous heap matters on the Pico W.
gc.collect()

# Import our modules. `gc.collect()` between groups keeps fragmentation low
# enough to start the second-core web-server thread (which needs ~4 KB
# contiguous for its stack).
from lib.config import TRANSITION_UPDATE_MS, NUM_LEDS, LED_START_OFFSET
from lib.storage import Storage
from lib.led_controller import LEDController
from lib.button_handler import ButtonHandler
gc.collect()
from lib.wifi_manager import WiFiManager
from lib.scheduler import Scheduler
from lib.sun_times import SunTimes
from lib.ntp_sync import NTPSync
from lib.tz_offset import TzOffset
gc.collect()
from lib.web_server import WebServer
from lib.game import Game
from lib.game2 import SimonGame, resolve_simon_button_map
from lib.game3 import MasterMindGame, resolve_mastermind_button_map
from lib.game_common import GameRegistry
gc.collect()


# Game-select carousel: ordered list of game slot names. F1 in lighting mode
# opens the carousel showing N centered white LEDs (one per slot); F1 cycles
# through them; F2 starts the highlighted slot. Adding a future game appends
# to this tuple.
_CAROUSEL_SLOTS = ("snake", "simon", "mastermind")

# Carousel timings
_CAROUSEL_IDLE_MS = 10000      # auto-close after 10 s of no F1/F2
_CAROUSEL_FLASH_MS = 250        # half-period of the white/yellow flash (2 Hz)


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
        # GameRegistry tracks every active-game so each can refuse-if-busy.
        # Snake doesn't inherit from BaseGame but exposes is_active(), which is
        # all the registry needs.
        self.registry = GameRegistry()
        self.game = Game(self.led, self.storage)
        self.registry.register(self.game)
        self.game.on_active_change = lambda active: self._on_game_active_change("snake", active)
        self.simon = SimonGame(self.led, self.storage, self.registry)
        self.simon.on_active_change = lambda active: self._on_game_active_change("simon", active)
        self.mastermind = MasterMindGame(self.led, self.storage, self.registry)
        self.mastermind.on_active_change = lambda active: self._on_game_active_change("mastermind", active)
        # Cache each game's button map so we only resolve it once per boot.
        self._simon_color_map = resolve_simon_button_map()
        self._mastermind_color_map = resolve_mastermind_button_map()
        self.web_server = WebServer(self.storage, self.wifi, self.scheduler, self.sun_times, self.ntp, self.tz_offset, self.game, self.simon, self.mastermind)

        # State
        self.last_transition_update = 0
        self.last_sun_times_update = 0
        self.last_ntp_sync = 0
        self.last_reboot_check = 0
        self.sun_times_update_interval = 3600000  # Update every hour
        self.ntp_sync_interval = 3600000  # Sync time every hour
        self.reboot_check_interval = 30000  # Check scheduled reboot every 30s
        self.web_server_running = False

        # Game-select carousel state
        self._carousel_active = False
        self._carousel_idx = 0
        self._carousel_idle_until = 0
        self._carousel_flash_yellow = False
        self._carousel_flash_next_toggle = 0

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
            # The second-core thread allocates ~4 KB contiguous for its stack.
            # Forcing a GC right before maximises the chance that block exists
            # without fragmentation.
            gc.collect()
            free = gc.mem_free() if hasattr(gc, "mem_free") else -1
            print(f"Starting web server on core 1... (free heap ~{free} B)")
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

    # ---------- Game-select carousel ----------

    def _carousel_open(self, now):
        if self._carousel_active:
            return
        print("Carousel: open")
        self._carousel_active = True
        self._carousel_idx = 0
        self._carousel_idle_until = time.ticks_add(now, _CAROUSEL_IDLE_MS)
        self._carousel_flash_yellow = False
        self._carousel_flash_next_toggle = time.ticks_add(now, _CAROUSEL_FLASH_MS)
        self.buttons.set_game_select_input_mode(True)
        # Render once immediately so the strip changes on this tick.
        self._carousel_render()

    def _carousel_close(self, reason):
        if not self._carousel_active:
            return
        print(f"Carousel: close ({reason})")
        self._carousel_active = False
        self.buttons.set_game_select_input_mode(False)
        # Clear the strip; the next _update_mode() tick will repaint per the
        # active lighting mode (auto/manual/off/rainbow).
        if self.led.enabled:
            for i in range(LED_START_OFFSET, NUM_LEDS):
                self.led.strip[i] = (0, 0, 0)
            self.led.strip.write()

    def _carousel_cycle(self, now):
        n = len(_CAROUSEL_SLOTS)
        if n <= 0:
            return
        self._carousel_idx = (self._carousel_idx + 1) % n
        self._carousel_idle_until = time.ticks_add(now, _CAROUSEL_IDLE_MS)
        # Reset the flash so the new selection LED starts on white.
        self._carousel_flash_yellow = False
        self._carousel_flash_next_toggle = time.ticks_add(now, _CAROUSEL_FLASH_MS)
        self._carousel_render()

    def _carousel_start_selected(self):
        if not _CAROUSEL_SLOTS:
            return
        slot = _CAROUSEL_SLOTS[self._carousel_idx]
        self._carousel_close("start " + slot)
        self._start_game_by_name(slot)

    def _carousel_tick(self, now):
        """Idle-timeout + flash animation. Called every main-loop iteration
        while the carousel is open."""
        # Idle timeout
        if time.ticks_diff(now, self._carousel_idle_until) >= 0:
            self._carousel_close("idle timeout")
            return
        # Flash
        if time.ticks_diff(now, self._carousel_flash_next_toggle) >= 0:
            self._carousel_flash_yellow = not self._carousel_flash_yellow
            self._carousel_flash_next_toggle = time.ticks_add(now, _CAROUSEL_FLASH_MS)
            self._carousel_render()

    def _carousel_render(self):
        """Paint the carousel onto the strip.

        N centered white LEDs (N = number of slots). The LED at position
        `_carousel_idx` (counting from the home end of the carousel block) is
        the cursor and alternates white<->yellow at 2 Hz; the other LEDs are
        solid full white.
        """
        if not self.led.enabled:
            return
        # Clear playable area first (LED 0 is the status LED — never touched).
        for i in range(LED_START_OFFSET, NUM_LEDS):
            self.led.strip[i] = (0, 0, 0)
        n = len(_CAROUSEL_SLOTS)
        if n <= 0:
            self.led.strip.write()
            return
        # Center N LEDs in the playable region [LED_START_OFFSET, NUM_LEDS-1].
        play_start = LED_START_OFFSET
        play_end = NUM_LEDS - 1
        play_len = play_end - play_start + 1
        if n >= play_len:
            # More slots than LEDs: just fill from home end and clamp the cursor.
            block_start = play_start
            block_len = play_len
        else:
            # Center; with mismatched parity, prefer the home-side pair.
            extra = play_len - n
            # Floor-divide so an odd 'extra' leaves the lone gap on the far side.
            offset = extra // 2
            block_start = play_start + offset
            block_len = n
        # Cursor LED first, then fill rest with solid white.
        cursor_offset = self._carousel_idx
        if cursor_offset >= block_len:
            cursor_offset = block_len - 1
        from lib.config import LED_BRIGHTNESS_MAX as _LB
        white = (_LB, _LB, _LB)
        # Yellow at full brightness — alternates with white at 2 Hz.
        yellow = (_LB, _LB, 0)
        for k in range(block_len):
            i = block_start + k
            if k == cursor_offset:
                self.led.strip[i] = yellow if self._carousel_flash_yellow else white
            else:
                self.led.strip[i] = white
        self.led.strip.write()

    # ---------- Game start dispatch ----------

    def _start_game_by_name(self, name):
        if name == "snake":
            self.game.start(1)
        elif name == "simon":
            self.simon.start()
        elif name == "mastermind":
            # Per §6.4: hardware start path enters length-select before play.
            self.mastermind.start(length=None)

    def _on_game_active_change(self, name, active):
        # Toggle button-input game mode whenever any game starts/stops. Each
        # game has its own preferred button-to-color map; switch the handler's
        # active map to match. last_game is persisted here too — single source
        # of truth.
        self.buttons.set_game_input_mode(active)
        if active:
            self.storage.set_last_game(name)
            if name == "simon":
                self.buttons.set_active_color_map(self._simon_color_map)
            elif name == "mastermind":
                self.buttons.set_active_color_map(self._mastermind_color_map)
            else:
                # snake (and any future game that wants snake's defaults)
                self.buttons.set_active_color_map(None)
        else:
            # Game ended — revert to snake defaults so the next press-edge
            # press during a fresh game start reads from a sensible map.
            self.buttons.set_active_color_map(None)

    def _update_mode(self):
        """Update LED state based on current mode"""
        if self.web_server and getattr(self.web_server, "preview_active", False):
            return
        # Carousel owns the strip while open: animation is driven by
        # _carousel_tick() in run(). Lighting mode is suppressed.
        if self._carousel_active:
            return
        # Pump every game every cycle. When inactive each one just drains
        # pending inputs so a queued start request transitions state in the
        # same loop iteration. Only one can be active (refuse-if-busy in
        # _try_begin), but ticking them all keeps the loop simple.
        self.game.tick()
        self.simon.tick()
        self.mastermind.tick()
        if self.registry.any_active():
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
                now = time.ticks_ms()

                active_game = self.registry.current_active()
                if active_game is self.game:
                    # Snake: pre-shot F1/F2 do level adjust; ALT+F1 aborts;
                    # F1-held-3s aborts.
                    if button_actions['abort_game'] or button_actions['f1_held_3s']:
                        print("Snake aborted (ALT+F1 or F1-held-3s)")
                        self.game.stop()
                    else:
                        delta = button_actions.get('level_delta', 0)
                        if delta and self.game.shots_fired_this_game() == 0:
                            new_level = max(1, self.game.level + delta)
                            print(f"Level adjust: {self.game.level} -> {new_level}")
                            self.game.restart_at_level(new_level)
                        else:
                            for c in button_actions.get('shoot_colors', ()):
                                self.game.shoot(c)
                elif active_game is self.simon:
                    # Simon: F1-held-3s aborts; every press-edge color is an
                    # input. Snake-specific level_delta / ALT+F1 abort signals
                    # are intentionally ignored here.
                    if button_actions['f1_held_3s']:
                        print("Simon aborted (F1-held-3s)")
                        self.simon.stop()
                    else:
                        for c in button_actions.get('shoot_colors', ()):
                            self.simon.input(c)
                elif active_game is self.mastermind:
                    # Master Mind: F1-held-3s aborts. While in length-select,
                    # F1 cycles and F2 confirms (no color input). During play,
                    # every press-edge color is an input — including whatever
                    # F1/F2/ALT happen to be mapped to. We disambiguate by
                    # looking at the game's phase.
                    if button_actions['f1_held_3s']:
                        print("Master Mind aborted (F1-held-3s)")
                        self.mastermind.stop()
                    elif self.mastermind.get_phase() == "length_select":
                        # Use raw button presses, not shoot_colors — F1/F2
                        # have a special meaning here. ALT and other keys are
                        # ignored per §6.4.
                        pressed = button_actions.get('pressed_buttons', ())
                        if 'f1' in pressed:
                            self.mastermind.select_cycle()
                        if 'f2' in pressed:
                            self.mastermind.select_confirm()
                    else:
                        for c in button_actions.get('shoot_colors', ()):
                            self.mastermind.input(c)
                elif self._carousel_active:
                    # Carousel: F1 cycles, F2 starts, F1-held-3s exits.
                    if button_actions['f1_held_3s']:
                        self._carousel_close("F1-held-3s")
                    elif button_actions['f1_short_press']:
                        self._carousel_cycle(now)
                    elif button_actions['f2_short_press']:
                        self._carousel_start_selected()
                    else:
                        self._carousel_tick(now)
                else:
                    # Lighting mode (no game, no carousel).
                    if button_actions['ap_mode']:
                        print("AP mode triggered by button combo")
                        self.web_server.stop()
                        self._start_ap_mode()
                        continue

                    # F1 short-press in lighting -> open carousel.
                    if button_actions.get('f1_short_press'):
                        print("F1 short-press: opening game-select carousel")
                        self._carousel_open(now)
                    # F2 short-press in lighting -> quick-start last game.
                    elif button_actions.get('f2_short_press'):
                        last = self.storage.get_last_game()
                        print(f"F2 short-press: quick-starting last game ({last})")
                        self._start_game_by_name(last)

                    # Handle mode changes from buttons
                    if button_actions['mode_change']:
                        temp = button_actions.get('mode_temporary')
                        if temp is None:
                            print(f"Mode changed to: {button_actions['mode_change']}")
                        else:
                            print(f"Mode changed to: {button_actions['mode_change']} (temporary={temp})")

                # Update status LED flash if active
                self.led.update_status_led_flash()

                # Update LED state based on mode (suppressed while carousel
                # is active; that path does its own rendering in _carousel_tick).
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
