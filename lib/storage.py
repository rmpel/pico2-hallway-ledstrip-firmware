# Non-volatile storage manager using JSON

import json
from config import (
    DEFAULT_SCHEDULE,
    DEFAULT_MANUAL_BRIGHTNESS,
    DEFAULT_MANUAL_HUE,
    DEFAULT_MANUAL_SATURATION,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_TIMEZONE,
    DEFAULT_REBOOT_TIME
)

WIFI_CONFIG_FILE = "/config.json"
SETTINGS_FILE = "/settings.json"


class Storage:
    def __init__(self):
        """Initialize storage and load config from files"""
        self.wifi_config = self._load_wifi_config()
        self.settings = self._load_settings()

    def _load_wifi_config(self):
        """Load WiFi configuration (separate file for security)"""
        try:
            with open(WIFI_CONFIG_FILE, 'r') as f:
                config = json.load(f)
                print(f"Loaded WiFi config from {WIFI_CONFIG_FILE}")

                # Handle old format migration
                if "wifi" in config:
                    print("Migrating old config format...")
                    wifi_config = config["wifi"]
                    # Save in new format
                    self._migrate_old_config(config)
                    return wifi_config
                else:
                    return config

        except (OSError, ValueError) as e:
            print(f"No WiFi config found, creating default: {e}")
            return {"ssid": None, "password": None}

    def _migrate_old_config(self, old_config):
        """Migrate old single-file config to new split format"""
        print("Migrating old config format to new split format...")

        # Extract WiFi config
        wifi_config = old_config.get("wifi", {"ssid": None, "password": None})

        # Extract settings
        old_loc = old_config.get("location", {})
        settings = {
            "location": {
                "latitude": old_loc.get("latitude", DEFAULT_LATITUDE),
                "longitude": old_loc.get("longitude", DEFAULT_LONGITUDE)
            },
            "manual": old_config.get("manual", {
                "brightness": DEFAULT_MANUAL_BRIGHTNESS,
                "hue": DEFAULT_MANUAL_HUE,
                "saturation": DEFAULT_MANUAL_SATURATION
            }),
            "schedule": old_config.get("schedule", DEFAULT_SCHEDULE),
            "mode": old_config.get("mode", "auto"),
            "tz_offset_seconds": 0,
            "tz_offset_updated": 0,
            "reboot_time": DEFAULT_REBOOT_TIME
        }

        # Save in new format
        try:
            with open(WIFI_CONFIG_FILE, 'w') as f:
                json.dump(wifi_config, f)
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(settings, f)
            print("Migration complete")
        except Exception as e:
            print(f"Migration failed: {e}")

    def _load_settings(self):
        """Load user settings from JSON file"""
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                print(f"Loaded settings from {SETTINGS_FILE}")
                # Ensure newer fields exist for older settings files.
                if "reboot_time" not in settings:
                    settings["reboot_time"] = DEFAULT_REBOOT_TIME
                if "non_auto_is_temporary" not in settings:
                    settings["non_auto_is_temporary"] = False
                if "hardware" not in settings or not isinstance(settings["hardware"], dict):
                    settings["hardware"] = {}
                if "game" not in settings or not isinstance(settings["game"], dict):
                    settings["game"] = {}
                if "game2" not in settings or not isinstance(settings["game2"], dict):
                    settings["game2"] = {}
                if "last_game" not in settings:
                    settings["last_game"] = "snake"
                return settings
        except (OSError, ValueError) as e:
            print(f"No settings file found, creating defaults: {e}")
            return self._create_default_settings()

    def _create_default_settings(self):
        """Create default settings"""
        return {
            "location": {
                "latitude": DEFAULT_LATITUDE,
                "longitude": DEFAULT_LONGITUDE
            },
            "manual": {
                "brightness": DEFAULT_MANUAL_BRIGHTNESS,
                "hue": DEFAULT_MANUAL_HUE,
                "saturation": DEFAULT_MANUAL_SATURATION
            },
            "schedule": DEFAULT_SCHEDULE,
            "mode": "auto",
            "tz_offset_seconds": 0,
            "tz_offset_updated": 0,
            "reboot_time": DEFAULT_REBOOT_TIME,
            "non_auto_is_temporary": False,
            "hardware": {},
            "game": {},
            "game2": {},
            "last_game": "snake"
        }

    def _save_wifi_config(self):
        """Save WiFi configuration"""
        try:
            with open(WIFI_CONFIG_FILE, 'w') as f:
                json.dump(self.wifi_config, f)
            print(f"WiFi config saved")
            return True
        except OSError as e:
            print(f"Failed to save WiFi config: {e}")
            return False

    def _save_settings(self):
        """Save user settings"""
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f)
            print(f"Settings saved")
            return True
        except OSError as e:
            print(f"Failed to save settings: {e}")
            return False

    # WiFi settings
    def get_wifi_ssid(self):
        return self.wifi_config.get("ssid")

    def get_wifi_password(self):
        return self.wifi_config.get("password")

    def set_wifi_credentials(self, ssid, password):
        self.wifi_config["ssid"] = ssid
        self.wifi_config["password"] = password
        self._save_wifi_config()

    def has_wifi_config(self):
        return self.wifi_config.get("ssid") is not None

    # Location settings
    def get_location(self):
        """Returns (latitude, longitude)"""
        loc = self.settings["location"]
        return (loc.get("latitude"), loc.get("longitude"))

    def set_location(self, latitude, longitude):
        self.settings["location"]["latitude"] = latitude
        self.settings["location"]["longitude"] = longitude
        self._save_settings()

    def has_location_config(self):
        loc = self.settings["location"]
        return loc.get("latitude") is not None and loc.get("longitude") is not None

    # Timezone offset (cached, refreshed from coords)
    def get_tz_offset_seconds(self):
        return int(self.settings.get("tz_offset_seconds", 0) or 0)

    def get_tz_offset_updated(self):
        return int(self.settings.get("tz_offset_updated", 0) or 0)

    def set_tz_offset(self, offset_seconds, updated_utc):
        self.settings["tz_offset_seconds"] = int(offset_seconds)
        self.settings["tz_offset_updated"] = int(updated_utc)
        self._save_settings()

    # Scheduled reboot time (HH:MM, device-local). Empty string disables.
    def get_reboot_time(self):
        return self.settings.get("reboot_time", DEFAULT_REBOOT_TIME) or ""

    def set_reboot_time(self, hhmm):
        self.settings["reboot_time"] = hhmm or ""
        self._save_settings()

    # When True, manually setting mode to off/on/rainbow only lasts until the
    # next schedule step boundary, then auto-resumes. Persisted (changes rarely).
    def get_non_auto_is_temporary(self):
        return bool(self.settings.get("non_auto_is_temporary", False))

    def set_non_auto_is_temporary(self, flag):
        self.settings["non_auto_is_temporary"] = bool(flag)
        self._save_settings()

    # Manual mode settings
    def get_manual_settings(self):
        """Returns (brightness, hue, saturation)"""
        m = self.settings["manual"]
        return (m["brightness"], m["hue"], m["saturation"])

    def set_manual_settings(self, brightness, hue, saturation):
        """Set all manual settings at once"""
        self.settings["manual"]["brightness"] = max(0, min(100, brightness))
        self.settings["manual"]["hue"] = max(0, min(360, hue))
        self.settings["manual"]["saturation"] = max(0, min(100, saturation))
        self._save_settings()

    def set_manual_brightness(self, brightness):
        self.settings["manual"]["brightness"] = max(0, min(100, brightness))
        self._save_settings()

    def set_manual_hue(self, hue):
        self.settings["manual"]["hue"] = max(0, min(360, hue))
        self._save_settings()

    def set_manual_saturation(self, saturation):
        self.settings["manual"]["saturation"] = max(0, min(100, saturation))
        self._save_settings()

    # Mode
    def get_mode(self):
        return self.settings.get("mode", "auto")

    def set_mode(self, mode):
        """Set mode: 'auto', 'on', 'rainbow', or 'off'"""
        if mode in ["auto", "on", "rainbow", "off"]:
            self.settings["mode"] = mode
            self._save_settings()

    # Schedule
    def get_schedule(self):
        return self.settings.get("schedule", [])

    def set_schedule(self, schedule):
        """
        Set schedule
        schedule: list of dicts with keys: event, offset, brightness, hue, saturation
        """
        self.settings["schedule"] = schedule
        self._save_settings()

    def add_schedule_step(self, step):
        """Add a schedule step"""
        if "schedule" not in self.settings:
            self.settings["schedule"] = []
        self.settings["schedule"].append(step)
        self._save_settings()

    def remove_schedule_step(self, index):
        """Remove a schedule step by index"""
        if 0 <= index < len(self.settings.get("schedule", [])):
            del self.settings["schedule"][index]
            self._save_settings()

    # Hardware settings (pin assignments, LED strip, button timings).
    # Applied at next reboot — config.py reads /settings.json at import time.
    def get_hardware_settings(self):
        return self.settings.get("hardware", {}) or {}

    def set_hardware_settings(self, hw_dict):
        self.settings["hardware"] = self._sanitize_hardware(hw_dict)
        self._save_settings()

    def _sanitize_hardware(self, hw_dict):
        """Filter to known keys and clamp to safe ranges.

        Lazy-imports config to read the canonical defaults dict; this avoids
        any import-order surprises at storage construction time.
        """
        if not isinstance(hw_dict, dict):
            return {}
        try:
            from config import _HARDWARE_DEFAULTS
        except ImportError:
            return {}

        pin_keys = (
            "pin_led_strip", "pin_button_off", "pin_button_auto", "pin_button_on",
            "pin_button_f1", "pin_button_f2", "pin_button_alt",
        )
        bool_keys = ("rp_pico_2_neopixel_compat_mode",)

        cleaned = {}
        for key, value in hw_dict.items():
            if key not in _HARDWARE_DEFAULTS:
                continue
            default = _HARDWARE_DEFAULTS[key]
            if key in bool_keys:
                cleaned[key] = bool(value)
                continue
            try:
                ivalue = int(value)
            except (TypeError, ValueError):
                continue
            if key in pin_keys:
                # Cover both RP2040 (0-28) and RP2350 (0-47).
                if 0 <= ivalue <= 47:
                    cleaned[key] = ivalue
            elif key == "num_leds":
                if ivalue >= 1:
                    cleaned[key] = ivalue
            elif key == "led_start_offset":
                if ivalue >= 0:
                    cleaned[key] = ivalue
            elif key == "led_brightness_max":
                if 1 <= ivalue <= 255:
                    cleaned[key] = ivalue
            elif key.endswith("_ms"):
                if ivalue >= 0:
                    cleaned[key] = ivalue
            elif key.endswith("_step"):
                if ivalue >= 1:
                    cleaned[key] = ivalue
            else:
                # Fallback: type-match the default.
                if isinstance(default, int):
                    cleaned[key] = ivalue
        return cleaned

    # Game settings (gameplay tunables for lib/game.py).
    # Applied at next reboot — game.py reads /settings.json at import time.
    def get_game_settings(self):
        return self.settings.get("game", {}) or {}

    def set_game_settings(self, game_dict):
        self.settings["game"] = self._sanitize_game(game_dict)
        self._save_settings()

    def _sanitize_game(self, game_dict):
        """Filter to known keys and clamp to safe ranges."""
        if not isinstance(game_dict, dict):
            return {}
        try:
            from game import _GAME_DEFAULTS
        except ImportError:
            return {}

        # Snake's color->button mapping. Sanitize separately and merge in below.
        buttons_clean = self._sanitize_button_map(
            game_dict.get("buttons"),
            ("shoot_red", "shoot_green", "shoot_blue",
             "shoot_yellow", "shoot_cyan", "shoot_magenta"),
        )

        # Dual-meaning keys: < 1 = fraction of playfield, >= 1 = exact LED
        # count. Only the lower bound (>= 0) is enforced here.
        dual_meaning_keys = (
            "barrier_fraction",
            "enemy_shield_fraction", "enemy_shield_fraction_per_level",
            "enemy_shield_fraction_max",
            "start_fraction", "max_fraction",
        )
        # True fractions: brightness intensities, must stay in [0.0, 1.0].
        brightness_keys = (
            "barrier_brightness", "enemy_shield_brightness",
        )
        nonneg_int_keys = (
            "home_skip_leds", "end_skip_leds",
            "grow_per_level", "ball_becomes_head_level",
        )
        positive_int_keys = (
            "grow_tick_ms", "grow_speedup_ms", "grow_tick_min_ms",
            "ball_tick_ms", "pending_shots_cap",
            "intro_flash_on_ms", "intro_flash_off_ms",
            "intro_hs_hold_ms", "intro_materialize_ms",
            "win_anim_step_ms", "win_fade_ms",
            "gameover_march_speedup",
        )

        cleaned = {}
        for key, value in game_dict.items():
            if key not in _GAME_DEFAULTS:
                continue
            if key in dual_meaning_keys:
                try:
                    fvalue = float(value)
                except (TypeError, ValueError):
                    continue
                if fvalue >= 0.0:
                    cleaned[key] = fvalue
            elif key in brightness_keys:
                try:
                    fvalue = float(value)
                except (TypeError, ValueError):
                    continue
                if 0.0 <= fvalue <= 1.0:
                    cleaned[key] = fvalue
            elif key in nonneg_int_keys:
                try:
                    ivalue = int(value)
                except (TypeError, ValueError):
                    continue
                if ivalue >= 0:
                    cleaned[key] = ivalue
            elif key in positive_int_keys:
                try:
                    ivalue = int(value)
                except (TypeError, ValueError):
                    continue
                if ivalue >= 1:
                    cleaned[key] = ivalue
        if buttons_clean:
            cleaned["buttons"] = buttons_clean
        return cleaned

    _BUTTON_NAMES = ("off", "auto", "on", "f1", "f2", "alt")

    def _sanitize_button_map(self, raw, allowed_actions):
        """Validate a {action_name: button_name} mapping. Drop unknown actions
        and unknown button-name values; missing entries are simply absent
        (callers fall back to per-game defaults)."""
        if not isinstance(raw, dict):
            return {}
        out = {}
        for action, btn in raw.items():
            if action not in allowed_actions:
                continue
            if btn in self._BUTTON_NAMES:
                out[action] = btn
        return out

    # Game 2 (Simon Says) settings — applied at next reboot. lib/game2.py reads
    # /settings.json at import time, mirroring how lib/game.py does it.
    def get_game2_settings(self):
        return self.settings.get("game2", {}) or {}

    def set_game2_settings(self, g2_dict):
        self.settings["game2"] = self._sanitize_game2(g2_dict)
        self._save_settings()

    def _sanitize_game2(self, g2_dict):
        if not isinstance(g2_dict, dict):
            return {}
        try:
            from game2 import _GAME2_DEFAULTS
        except ImportError:
            return {}

        buttons_clean = self._sanitize_button_map(
            g2_dict.get("buttons"),
            ("input_red", "input_green", "input_blue", "input_yellow"),
        )

        # Playfield bounds: ints, but end_led may be -1 (= last LED).
        # Other ms / count fields: positive ints.
        positive_int_keys = (
            "flash_on_ms", "flash_off_ms",
            "input_timeout_ms", "press_feedback_ms",
            "result_flash_ms", "result_flash_count",
            "score_display_ms",
        )

        cleaned = {}
        for key, value in g2_dict.items():
            if key not in _GAME2_DEFAULTS:
                continue
            if key == "playfield_start_led":
                try:
                    ivalue = int(value)
                except (TypeError, ValueError):
                    continue
                if ivalue >= 0:
                    cleaned[key] = ivalue
            elif key == "playfield_end_led":
                try:
                    ivalue = int(value)
                except (TypeError, ValueError):
                    continue
                # -1 sentinel = "last LED"; otherwise must be >= 0.
                if ivalue == -1 or ivalue >= 0:
                    cleaned[key] = ivalue
            elif key in positive_int_keys:
                try:
                    ivalue = int(value)
                except (TypeError, ValueError):
                    continue
                if ivalue >= 1:
                    cleaned[key] = ivalue
        if buttons_clean:
            cleaned["buttons"] = buttons_clean
        # input_timeout_ms must be a whole number of seconds (per §5.4a) so the
        # countdown LED pops land on full-second boundaries. Round down.
        if "input_timeout_ms" in cleaned:
            cleaned["input_timeout_ms"] = max(1000, (cleaned["input_timeout_ms"] // 1000) * 1000)
        return cleaned

    # Last-played game. Used by F2 quick-start in lighting mode.
    _LAST_GAME_VALID = ("snake", "simon", "mastermind")

    def get_last_game(self):
        v = self.settings.get("last_game", "snake")
        return v if v in self._LAST_GAME_VALID else "snake"

    def set_last_game(self, name):
        if name in self._LAST_GAME_VALID:
            self.settings["last_game"] = name
            self._save_settings()

    def get_all_settings(self):
        """Get all settings (for web API) - excludes WiFi credentials"""
        return self.settings

    def update_settings(self, new_settings):
        """Update settings (for web API) - excludes WiFi credentials"""
        for key in new_settings:
            if key == "mode":
                continue
            if key == "location" and isinstance(new_settings[key], dict):
                loc = {
                    "latitude": new_settings[key].get("latitude"),
                    "longitude": new_settings[key].get("longitude")
                }
                self.settings["location"] = loc
            elif key == "hardware":
                self.settings["hardware"] = self._sanitize_hardware(new_settings[key])
            elif key == "game":
                self.settings["game"] = self._sanitize_game(new_settings[key])
            elif key == "game2":
                self.settings["game2"] = self._sanitize_game2(new_settings[key])
            elif key == "last_game":
                v = new_settings[key]
                if v in self._LAST_GAME_VALID:
                    self.settings["last_game"] = v
            else:
                self.settings[key] = new_settings[key]
        self._save_settings()
