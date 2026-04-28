# HallwayLedBar

A smart LED strip controller for hallway mood lighting using a Raspberry Pi Pico W, featuring:

- Sunrise/sunset scheduling with configurable transitions
- Web-based configuration interface
- Physical button controls
- HSV color control (Hue, Saturation, Brightness)
- Auto/Manual/Off modes
- Smooth color and brightness transitions

## Hardware Requirements

- Raspberry Pi Pico W
- WS2812 LED strip (30 LEDs/m)
- 3 push buttons
- 12A power supply (for LED strip)
- Power supply for Pico W (USB or separate 5V)
- Resistors for buttons (optional, internal pull-ups used)

## Wiring Diagram

```
┌─────────────────────────────────────┐
│   Raspberry Pi Pico W               │
│                                     │
│  GP15 ──────────────── WS2812 Data  │ ──► LED Strip
│  GND  ──────────────── WS2812 GND   │
│                                     │
│  GP16 ──┬──────────── OFF Button    │ ──► GND
│         └── (internal pull-up)      │
│                                     │
│  GP17 ──┬──────────── AUTO Button   │ ──► GND
│         └── (internal pull-up)      │
│                                     │
│  GP18 ──┬──────────── ON Button     │ ──► GND
│         └── (internal pull-up)      │
│                                     │
│  VBUS ─────────────── USB 5V        │
│  GND  ─────────────── USB GND       │
└─────────────────────────────────────┘

LED Strip Power:
  12A Power Supply (+) ──► WS2812 VCC
  12A Power Supply (-) ──► WS2812 GND + Pico GND (common ground!)
```

### Important Notes:

1. **Common Ground**: LED strip ground MUST be connected to Pico W ground
2. **Power Supply**: WS2812 strips need significant current - use a 12A supply for safety
3. **Data Line**: GP15 connects directly to WS2812 DIN (first LED in strip)
4. **Buttons**: Active-low with internal pull-ups (press = connect to GND)
5. **Power Supply Noise**: Switching power supplies (including quality brands like Mean Well RS-75) can produce audible coil whine when driving WS2812 LEDs due to PWM frequencies. This is normal and not harmful. To reduce noise, add a large electrolytic capacitor (2200-4700µF, 10V+) directly across the LED strip power input (VCC to GND). Ensure correct polarity!

### GPIO Pin Assignments

| GPIO | Function          | Notes                    |
|------|-------------------|--------------------------|
| GP15 | WS2812 Data       | Configurable in config.py|
| GP16 | OFF Button        | Active-low, pull-up      |
| GP17 | AUTO Button       | Active-low, pull-up      |
| GP18 | ON Button         | Active-low, pull-up      |

## Software Setup

### First Time Installation

1. **Install dependencies** (run once on your Mac):
   ```bash
   ./install.sh
   ```

2. **Flash MicroPython to Pico W**:
   - Hold the BOOTSEL button on your Pico W
   - Plug in the USB cable (while holding BOOTSEL)
   - A drive named "RPI-RP2" will appear
   - Drag `RPI_PICO_W-latest.uf2` to the drive
   - Wait for Pico W to reboot

3. **Deploy code to Pico W**:
   ```bash
   ./deploy.sh
   ```

### Updating Code

After making changes to the code:

```bash
./deploy.sh
```

## Initial Configuration

### WiFi Setup (First Boot)

On first boot, the Pico W will enter Access Point mode automatically:

1. Look for a WiFi network named `PicoW-LedBar-XXXX`
2. Connect to it (no password required - open network for setup only)
3. Open browser to `http://192.168.4.1`
4. Enter your WiFi credentials
5. Device will test connection and reboot if successful

### Manual AP Mode

To re-enter AP mode later:

1. Press and hold all 3 buttons for 10 seconds
2. LED strip will flash white
3. Connect to the AP as described above

## Usage

### Button Controls

**Single Press:**
- OFF button: Set mode to "Off" (LEDs off)
- AUTO button: Set mode to "Auto" (follow schedule)
- ON button: Set mode to "On" (manual control)

**Press and Hold (in "On" mode only):**
- ON button: Adjust brightness up/down (alternates each hold)
- OFF button: Rotate hue left/right (alternates each hold)
- AUTO button: Adjust saturation up/down (alternates each hold)

**All 3 buttons held for 10 seconds:**
- Enter WiFi setup (AP mode)

### Web Interface

Connect to your Pico W's IP address in a web browser.

**Status Section:**
- Current mode (Off/Auto/On)
- WiFi connection status
- Next scheduled event

**Mode Control:**
- Quick buttons to switch between Off/Auto/On

**Location Settings:**
- Set latitude, longitude, and timezone
- Required for sunrise/sunset calculations
- Example: Amsterdam = 52.3676, 4.9041, Europe/Amsterdam

**Schedule Editor:**
- Add/remove schedule steps
- Drag and drop to reorder steps
- Each step configures:
  - Event: Sunrise or Sunset
  - Offset: Minutes before/after event (negative = before)
  - Brightness: 0-100%
  - Hue: 0-360° (0=red, 120=green, 240=blue)
  - Saturation: 0-100% (0=white, 100=full color)

### Example Schedule

Create a warm sunset-to-night transition:

1. Sunset - 15 min: 5% brightness, hue 30° (warm orange), 100% saturation
2. Sunset + 3 hours: 50% brightness, hue 180° (cyan), 100% saturation
3. Sunset + 5 hours: 50% brightness, hue 240° (blue), 80% saturation
4. Sunset + 5h 1min: 0% brightness (off)
5. Sunrise - 1 hour: 50% brightness, hue 20° (warm), 100% saturation
6. Sunrise + 15 min: 5% brightness, hue 40° (orange), 100% saturation
7. Sunrise + 1 hour: 0% brightness (off)

All transitions are smooth and gradual over the time between steps.

## Configuration

Edit `lib/config.py` to customize:

- GPIO pin assignments
- LED strip length (NUM_LEDS)
- Button timing (debounce, hold duration)
- Adjustment speeds (brightness/hue/saturation steps)
- Transition update interval
- Default schedule
- AP mode password (change from 87654321 for security!)

## Troubleshooting

### LEDs don't light up
- Check common ground between Pico W and LED strip
- Verify WS2812 data pin (GP15)
- Check LED strip power supply
- Verify NUM_LEDS in lib/config.py matches your actual LED count

### Only some LEDs light up
- Check NUM_LEDS setting in lib/config.py (default is 60 for 2 meters at 30 LEDs/m)
- Adjust LED_START_OFFSET if you want to skip first N LEDs

### Power supply makes noise (coil whine)
- Normal with WS2812 LEDs, especially at certain brightness/color combinations
- Add large electrolytic capacitor (2200-4700µF, 10V+) across LED strip power input
- Try different brightness levels - noise may be worse at specific PWM duty cycles
- Mechanically isolate PSU with rubber feet/foam padding

### Can't connect to WiFi
- Hold all 3 buttons for 10 seconds to re-enter AP mode
- Check WiFi credentials in web interface
- Ensure 2.4GHz WiFi (Pico W doesn't support 5GHz)

### Buttons don't respond
- Check button wiring (active-low, connect to GND)
- Verify GPIO pin assignments in config.py
- Check for loose connections

### Schedule doesn't work
- Verify location is configured (latitude/longitude/timezone)
- Check WiFi connection (needed to fetch sunrise/sunset times)
- Ensure mode is set to "Auto"

### Web interface unreachable
- Check Pico W IP address (displayed in REPL console)
- Ensure Pico W and your device are on same network
- Try connecting via serial: `mpremote connect repl`

## Monitoring & Debugging

Connect to the Pico W's serial console:

```bash
mpremote connect repl
```

Press Ctrl-D to soft reboot and see startup messages.

## File Structure

```
/
├── install.sh              # One-time setup script
├── deploy.sh               # Deploy code to Pico W
├── main.py                 # Main program
├── lib/
│   ├── config.py           # Configuration defaults
│   ├── led_controller.py   # WS2812 control + HSV
│   ├── scheduler.py        # Schedule engine
│   ├── sun_times.py        # Sunrise/sunset API
│   ├── web_server.py       # HTTP server
│   ├── storage.py          # Non-volatile storage
│   ├── wifi_manager.py     # WiFi + AP mode
│   └── button_handler.py   # Button input handling
├── web/
│   ├── index.html          # Main UI
│   ├── setup.html          # WiFi setup UI
│   └── style.css           # Styles
└── README.md               # This file
```

## License

MIT License - feel free to modify and use as you wish!

## Credits

Built with MicroPython for Raspberry Pi Pico W.
