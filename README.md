# HallwayLedBar

A smart LED strip controller for hallway mood lighting using a Raspberry Pi Pico W, featuring:

- Sunrise/sunset scheduling with configurable transitions
- Web-based configuration interface
- 6-button physical control panel (mode + function rows)
- HSV color control (Hue, Saturation, Brightness)
- Off / Auto / On / Rainbow modes, plus an interactive **Game mode** (see [GAME.md](GAME.md))
- Smooth color and brightness transitions

## Hardware Requirements

- Raspberry Pi Pico W
- WS2812 LED strip (30 LEDs/m)
- 6 push buttons (3 mode + 3 function)
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
│  Row 1 (mode panel):                │
│  GP16 ──┬──────────── OFF Button    │ ──► GND
│  GP17 ──┬──────────── AUTO Button   │ ──► GND
│  GP18 ──┬──────────── ON Button     │ ──► GND
│         └── (internal pull-up)      │
│                                     │
│  Row 2 (function panel):            │
│  GP20 ──┬──────────── F1 Button     │ ──► GND
│  GP21 ──┬──────────── F2 Button     │ ──► GND
│  GP22 ──┬──────────── ALT Button    │ ──► GND
│         └── (internal pull-up)      │
│                                     │
│  VBUS ─────────────── USB 5V        │
│  GND  ─────────────── USB GND       │
└─────────────────────────────────────┘

LED Strip Power:
  12A Power Supply (+) ──► WS2812 VCC
  12A Power Supply (-) ──► WS2812 GND + Pico GND (common ground!)
```

### Important Notes

1. **Common Ground**: LED strip ground MUST be connected to Pico W ground.
2. **Power Supply**: WS2812 strips need significant current — use a 12A supply for safety.
3. **Data Line**: GP15 connects directly to WS2812 DIN (first LED in strip).
4. **Buttons**: Active-low with internal pull-ups (press = connect to GND).
5. **Power Supply Noise**: Switching supplies can produce coil whine when driving WS2812 LEDs at certain PWM duty cycles. Add a 2200–4700µF 10V+ electrolytic across the LED strip power input to reduce it.

### GPIO Pin Assignments

| GPIO | Function       | Notes                       |
|------|----------------|-----------------------------|
| GP15 | WS2812 Data    | Configurable in `config.py` |
| GP16 | OFF Button     | Active-low, pull-up         |
| GP17 | AUTO Button    | Active-low, pull-up         |
| GP18 | ON Button      | Active-low, pull-up         |
| GP20 | F1 Button      | Active-low, pull-up         |
| GP21 | F2 Button      | Active-low, pull-up         |
| GP22 | ALT Button     | Active-low, pull-up         |

LED 0 of the strip is reserved as a small **status LED** (WiFi state, button-press blip, etc.). Playfield/effects use LEDs 1+.

## Operation Modes

Modes are persisted to `settings.json` and survive reboot.

| Mode       | Description |
|------------|-------------|
| **Off**    | All LEDs dark. |
| **Auto**   | The schedule engine drives the strip — it interpolates between schedule steps anchored to clock times or sunrise/sunset offsets. |
| **On**     | Manual fixed-color mode. Brightness/hue/saturation are set via web UI or by holding row-1 buttons (see below). |
| **Rainbow**| Animated full-spectrum rainbow across the strip. Saturation and brightness from manual settings; hue is animated. |
| **Game**   | An in-RAM game mode (see [GAME.md](GAME.md)) that takes over the LED strip without altering the persisted mode. When the game ends/aborts, the previous mode resumes. |

When the device is in Off, On, or Rainbow with the **"Resume schedule at next event"** flag enabled (`non_auto_is_temporary=True`), the scheduler watches for the next schedule-step boundary and automatically returns to Auto. This makes physical-button overrides naturally lapse instead of staying forever.

## Software Setup

### First Time Installation

1. Install dependencies (run once on your Mac):
   ```bash
   ./install.sh
   ```
2. Flash MicroPython to the Pico W:
   - Hold the BOOTSEL button on your Pico W
   - Plug in the USB cable (while holding BOOTSEL)
   - A drive named "RPI-RP2" appears
   - Drag `RPI_PICO_W-latest.uf2` to the drive
   - Wait for the Pico W to reboot
3. Deploy code to the Pico W:
   ```bash
   ./deploy.sh
   ```

### Updating Code

```bash
./deploy.sh                    # full deploy via USB
./deploy-wireless.sh <ip> ...  # incremental deploy over WiFi
./picp <file>                  # deploy a single file (recommended for iterating)
```

Reboot the device after any `.py` change. Web assets (`/web/*`) take effect on next request.

## Initial Configuration

### WiFi Setup (First Boot)

On first boot, the Pico W enters Access Point mode automatically:

1. Look for a WiFi network named `PicoW-LedBar-XXXX`.
2. Connect (no password — open network for setup only).
3. Open browser to `http://192.168.4.1`.
4. Enter your WiFi credentials.
5. Device tests the connection and reboots if successful.

### Manual AP Mode

To re-enter AP mode later: hold all 3 row-1 buttons (OFF + AUTO + ON) for 10 seconds. The status LED will reflect AP-mode state.

## Button Reference

The panel has two rows of three buttons each. Row 1 is the **mode panel** (OFF/AUTO/ON); row 2 is the **function panel** (F1/F2/ALT). ALT is a modifier — held during another button press.

ALT counts as the modifier whether it was held when the other button was *pressed* OR is still held when the other button is *released* — so order is forgiving.

### Lighting mode (game inactive)

| Button   | Push (release < 1s)                              | Hold (≥ 1s)                                         | Push + ALT                              |
|----------|---------------------------------------------------|------------------------------------------------------|-----------------------------------------|
| **OFF**  | mode = off, **temporary** (auto-resume on schedule event) | While mode==on: cycle hue ±5°/100ms, direction locked per hold; flips on release | mode = off, **permanent** (no auto-resume) |
| **AUTO** | mode = auto                                       | While mode==on: cycle saturation ±2/100ms, direction locked per hold; flips on release | mode = rainbow, **temporary**           |
| **ON**   | mode = on, **temporary**                          | While mode==on: cycle brightness ±2/100ms, direction locked per hold; flips on release | mode = on, **permanent**                |
| **F1**   | start a game (level 1)                            | —                                                   | start a game (ALT ignored outside game) |
| **F2**   | —                                                 | —                                                   | —                                       |
| **ALT**  | —                                                 | —                                                   | (n/a)                                   |

**Combos (lighting mode):**
- OFF + AUTO + ON held simultaneously for 10s → enter AP mode (WiFi setup).

### Game mode

Buttons in game mode are documented in [GAME.md](GAME.md). Short summary: each of the 6 buttons fires one ball of its assigned color (row 1 = R/G/B, row 2 = Y/C/M). F1/F2 adjust the starting level if pressed before any ball is fired this game. ALT+F1 aborts the game and returns to lighting mode.

### Status LED feedback

Every button press triggers a brief (~30ms) blue blip on LED 0, so you get tactile confirmation that the press registered even when the action itself does nothing visible.

## Web Interface

Connect to your Pico W's IP address in a web browser.

**Status section:** mode, WiFi, time (UTC/local/browser), upcoming schedule events.

**Mode control:** quick buttons to switch between Off / Auto / On / Rainbow, and a "Resume schedule at next event" toggle for the temporary-override behavior.

**Manual color control:** sliders for hue/saturation/brightness used by On and Rainbow modes.

**Schedule editor:** add/remove schedule steps. Each step configures:
- Event: sunrise or sunset, OR a fixed local time
- Offset (event-anchored): minutes before/after event (negative = before)
- Brightness 0–100%
- Hue 0–360° (0=red, 120=green, 240=blue)
- Saturation 0–100% (0=white, 100=full color)

**Setup page:** location, nightly reboot time.

**File management:** browse and download files from the device. Useful for grabbing `settings.json` or `game.json` for backup.

**Game:** "Start game" link → opens the [Game UI](GAME.md#web-game-ui).

### Example Schedule

A warm sunset-to-night transition:

1. Sunset − 15 min: 5% brightness, hue 30° (warm orange), 100% saturation
2. Sunset + 3 hours: 50% brightness, hue 180° (cyan), 100% saturation
3. Sunset + 5 hours: 50% brightness, hue 240° (blue), 80% saturation
4. Sunset + 5h 1min: 0% brightness (off)
5. Sunrise − 1 hour: 50% brightness, hue 20° (warm), 100% saturation
6. Sunrise + 15 min: 5% brightness, hue 40° (orange), 100% saturation
7. Sunrise + 1 hour: 0% brightness (off)

Transitions interpolate smoothly over the time between steps.

## Configuration

Edit `lib/config.py` to customize:

- GPIO pin assignments (LED data, buttons, game-button alias mapping)
- LED strip length (`NUM_LEDS`)
- Button timing (`BUTTON_DEBOUNCE_MS`, `BUTTON_HOLD_MS`, `BUTTON_COMBO_MS`)
- Adjustment speeds (`BRIGHTNESS_STEP`, `HUE_STEP`, `SATURATION_STEP`)
- Transition update interval
- Default schedule
- AP mode SSID prefix and password

Game-specific tunables live at the top of `lib/game.py` — see [GAME.md](GAME.md#tunables).

## Troubleshooting

### LEDs don't light up
- Check common ground between Pico W and LED strip
- Verify WS2812 data pin (GP15)
- Check LED strip power supply
- Verify NUM_LEDS in `lib/config.py` matches your actual LED count

### Only some LEDs light up
- Check `NUM_LEDS` in `lib/config.py`
- Adjust `LED_START_OFFSET` to skip first N LEDs (LED 0 is the status LED)

### Power supply makes noise (coil whine)
- Normal with WS2812 LEDs at certain brightness/color combinations
- Add 2200–4700µF 10V+ electrolytic across LED strip power input
- Mechanically isolate PSU with rubber feet/foam padding

### Can't connect to WiFi
- Hold OFF + AUTO + ON for 10s to re-enter AP mode
- Check credentials in the web interface
- Ensure 2.4 GHz WiFi (Pico W doesn't support 5 GHz)

### Buttons don't respond
- Check wiring (active-low, connect pin to GND on press)
- Verify GPIO pin assignments in `config.py`
- Diagnostic: the serial console emits a `BTN ...` line whenever the held-button snapshot changes — you can see exactly which pins are reading pressed:
  ```
  BTN -off- -auto- -on- -f1- -f2- -alt-           ← all released
  BTN -off- [AUTO] -on- -f1- -f2- -alt-           ← AUTO held
  BTN [OFF] -auto- [ON] -f1- -f2- [ALT]           ← three held
  ```
- Every press should also produce a brief blue blip on LED 0.

### Schedule doesn't work
- Verify location is configured
- Check WiFi connection (needed to fetch sunrise/sunset)
- Ensure mode is Auto

### Web interface unreachable
- Check Pico W IP (printed in the REPL on boot)
- Ensure Pico W and your device are on the same network
- Try serial: `mpremote connect repl`

## Monitoring & Debugging

```bash
mpremote connect repl
```

Press Ctrl-D to soft reboot and see startup messages.

## File Structure

```
/
├── install.sh              # One-time setup script
├── deploy.sh               # Full deploy via USB
├── deploy-wireless.sh      # Full deploy over WiFi
├── picp                    # Single-file incremental deploy
├── main.py                 # Main program (orchestrator + main loop)
├── lib/
│   ├── config.py           # Configuration defaults (pins, timings, schedule)
│   ├── led_controller.py   # WS2812 control + HSV + status LED
│   ├── scheduler.py        # Schedule engine (sunrise/sunset, interpolation)
│   ├── sun_times.py        # Sunrise/sunset API + tz offset
│   ├── tz_offset.py        # Timezone offset cache
│   ├── ntp_sync.py         # NTP time sync
│   ├── web_server.py       # HTTP server + REST API
│   ├── storage.py          # Non-volatile JSON storage
│   ├── wifi_manager.py     # WiFi + AP mode
│   ├── button_handler.py   # 6-button input + ALT modifier + game-mode dispatch
│   └── game.py             # Color-matching game (see GAME.md)
├── web/
│   ├── index.html          # Main control UI
│   ├── setup.html          # WiFi setup UI
│   ├── options.html        # Setup page (location, reboot time)
│   ├── files.html          # File management UI
│   ├── game.html           # Game UI
│   ├── script.js, options.js, files.js, game.js
│   └── style.css
├── README.md               # This file
└── GAME.md                 # Game mode documentation
```

## License

MIT License — feel free to modify and use as you wish.

## Credits

Built with MicroPython for Raspberry Pi Pico W.

## PROXY SERVICE

SSL is problematic for a classic Pico, use a proxy service, see the proxy directory for a PHP implementation.
Create a (sub)domain somewhere that runs HTTP, place the index file, set-up the proxy in settings.
