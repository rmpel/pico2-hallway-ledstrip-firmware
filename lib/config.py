# Configuration for HallwayLedBar
#
# This module exposes flat module-level constants so existing
# `from config import NAME` imports keep working unchanged.
#
# Hardware-related values (pins, LED count, button timings, etc.) are
# overridable via /settings.json under a "hardware" key. Overrides are read
# once at module import time, so changes take effect on the next reboot.
# Unknown keys in the JSON are ignored; missing keys fall back to the
# defaults below.

import json

# Access Point settings (for WiFi setup mode) — never overridable
AP_SSID_PREFIX = "PicoW-LedBar"
AP_IP = "192.168.4.1"

# Schedule transition update interval (milliseconds)
# (Made overridable below alongside other hardware tunables.)

# Sunrise/sunset API settings — not user-editable
SUN_TIMES_API = "https://api.sunrise-sunset.org/json"
SUN_TIMES_CACHE_HOURS = 12  # Re-fetch every 12 hours

# Legacy single-file config path (kept for back-compat references)
STORAGE_FILE = "/config.json"

# Hardware / UX defaults. Used when /settings.json does not override a key.
# This dict is also the allow-list for runtime updates from the web UI.
_HARDWARE_DEFAULTS = {
    # GPIO pins (six canonical buttons; game color-to-button mapping lives
    # under each game's settings block, not as a parallel set of pins).
    "pin_led_strip": 15,
    "pin_button_off": 16,
    "pin_button_auto": 17,
    "pin_button_on": 18,
    "pin_button_f1": 20,
    "pin_button_f2": 21,
    "pin_button_alt": 22,
    # LED strip
    "num_leds": 12,
    "led_start_offset": 0,
    "led_brightness_max": 255,
    "rp_pico_2_neopixel_compat_mode": True,
    # Button timing (milliseconds)
    "button_debounce_ms": 50,
    "button_hold_ms": 1000,
    "button_combo_ms": 10000,
    # Manual adjustment speeds (per 100ms while holding button)
    "brightness_step": 2,
    "hue_step": 5,
    "saturation_step": 2,
    # Schedule transition update interval (milliseconds)
    "transition_update_ms": 1000,
    # Optional HTTP proxy for outbound API calls. Pico W's TLS handshake
    # needs a 30-50 KB contiguous heap block which routinely fails after
    # the app's modules are loaded — point this at a plain-HTTP proxy that
    # URL-decodes its `_` query param to bypass on-device TLS. Empty string
    # disables the proxy (direct HTTPS).
    # Value is the bare hostname (e.g. "http-proxy.example.com"); the
    # firmware adds the http:// prefix, the trailing /?_= and URL-encoded
    # upstream URL.
    "http_proxy": "",
}


def _load_hardware_overrides():
    """Read /settings.json and return its 'hardware' dict, or {} on any error.

    Failing open keeps the device bootable even if the settings file is
    missing, truncated, or corrupt — the defaults above still apply.
    """
    try:
        with open("/settings.json", "r") as f:
            data = json.load(f)
        hw = data.get("hardware") if isinstance(data, dict) else None
        return hw if isinstance(hw, dict) else {}
    except (OSError, ValueError):
        return {}


_overrides = _load_hardware_overrides()


def _h(key):
    return _overrides.get(key, _HARDWARE_DEFAULTS[key])


# GPIO pins
PIN_LED_STRIP = _h("pin_led_strip")
PIN_BUTTON_OFF = _h("pin_button_off")
PIN_BUTTON_AUTO = _h("pin_button_auto")
PIN_BUTTON_ON = _h("pin_button_on")
PIN_BUTTON_F1 = _h("pin_button_f1")
PIN_BUTTON_F2 = _h("pin_button_f2")
PIN_BUTTON_ALT = _h("pin_button_alt")

# LED strip
NUM_LEDS = _h("num_leds")
LED_START_OFFSET = _h("led_start_offset")
LED_BRIGHTNESS_MAX = _h("led_brightness_max")
RP_PICO_2_NEOPIXEL_COMPAT_MODE = _h("rp_pico_2_neopixel_compat_mode")

# Button timing
BUTTON_DEBOUNCE_MS = _h("button_debounce_ms")
BUTTON_HOLD_MS = _h("button_hold_ms")
BUTTON_COMBO_MS = _h("button_combo_ms")

# Manual adjustment speeds
BRIGHTNESS_STEP = _h("brightness_step")
HUE_STEP = _h("hue_step")
SATURATION_STEP = _h("saturation_step")

# Scheduler
TRANSITION_UPDATE_MS = _h("transition_update_ms")

# Outbound HTTP proxy (empty = disabled, direct HTTPS)
HTTP_PROXY = _h("http_proxy")

# Default schedule (example) — fallback when /settings.json has no schedule
DEFAULT_SCHEDULE = [
    {"event": "sunset", "offset": -15, "brightness": 5, "hue": 30, "saturation": 100},
    {"event": "sunset", "offset": 180, "brightness": 50, "hue": 180, "saturation": 100},
    {"event": "sunset", "offset": 300, "brightness": 50, "hue": 240, "saturation": 80},
    {"event": "sunset", "offset": 301, "brightness": 0, "hue": 0, "saturation": 0},
    {"event": "sunrise", "offset": -60, "brightness": 50, "hue": 20, "saturation": 100},
    {"event": "sunrise", "offset": 15, "brightness": 5, "hue": 40, "saturation": 100},
    {"event": "sunrise", "offset": 60, "brightness": 0, "hue": 0, "saturation": 0},
]

# Default manual mode settings
DEFAULT_MANUAL_BRIGHTNESS = 100
DEFAULT_MANUAL_HUE = 180
DEFAULT_MANUAL_SATURATION = 100

# Default location (must be configured via web UI)
DEFAULT_LATITUDE = None
DEFAULT_LONGITUDE = None
DEFAULT_TIMEZONE = "UTC"

# Nightly scheduled reboot (HH:MM, device-local). Empty string disables.
DEFAULT_REBOOT_TIME = "03:00"
