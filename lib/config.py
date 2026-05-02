# Configuration defaults for HallwayLedBar

# Access Point settings (for WiFi setup mode)
AP_SSID_PREFIX = "PicoW-LedBar"
AP_PASSWORD = "hallway123"
AP_IP = "192.168.4.1"

# GPIO pins
PIN_LED_STRIP = 15  # WS2812 data pin
# Row 1 (mode panel): off / auto / on
PIN_BUTTON_OFF = 16
PIN_BUTTON_AUTO = 17
PIN_BUTTON_ON = 18
# Row 2 (function/modifier panel): F1 / F2 / ALT
PIN_BUTTON_F1 = 20
PIN_BUTTON_F2 = 21
PIN_BUTTON_ALT = 22

# Game button mapping (default to existing physical buttons; tweak per pin once wired)
PIN_BUTTON_R = PIN_BUTTON_OFF
PIN_BUTTON_G = PIN_BUTTON_AUTO
PIN_BUTTON_B = PIN_BUTTON_ON

# LED strip configuration
NUM_LEDS = 76  # 2 meters at 30 LEDs/meter
LED_START_OFFSET = 1  # Skip first N LEDs (LED 0 is status LED)
LED_BRIGHTNESS_MAX = 255

# Button timing (milliseconds)
BUTTON_DEBOUNCE_MS = 50
BUTTON_HOLD_MS = 1000  # How long to hold for continuous adjust
BUTTON_COMBO_MS = 10000  # All 3 buttons for AP mode (10 seconds)

# Manual adjustment speeds (per 100ms while holding button)
BRIGHTNESS_STEP = 2  # 0-100 scale
HUE_STEP = 5  # 0-360 degrees
SATURATION_STEP = 2  # 0-100 scale

# Schedule transition update interval (milliseconds)
TRANSITION_UPDATE_MS = 1000

# Sunrise/sunset API settings
SUN_TIMES_API = "https://api.sunrise-sunset.org/json"
SUN_TIMES_CACHE_HOURS = 12  # Re-fetch every 12 hours

# Storage file path
STORAGE_FILE = "/config.json"

# Default schedule (example)
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
