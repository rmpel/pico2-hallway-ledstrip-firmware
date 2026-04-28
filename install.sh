#!/bin/bash

# HallwayLedBar - One-time setup script
# Installs dependencies and downloads MicroPython firmware

set -e

echo "🔧 HallwayLedBar Setup"
echo "====================="
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    echo "   Install from: https://www.python.org/downloads/"
    exit 1
fi

echo "✓ Python 3 found"

# Install mpremote for deploying to Pico W
echo ""
echo "📦 Installing mpremote..."
pip3 install --upgrade mpremote

echo ""
echo "⬇️  Downloading MicroPython firmware for Pico W..."
MICROPYTHON_URL="https://micropython.org/download/RPI_PICO_W/RPI_PICO_W-latest.uf2"
FIRMWARE_FILE="RPI_PICO_W-latest.uf2"

if [ -f "$FIRMWARE_FILE" ]; then
    echo "   Firmware already downloaded: $FIRMWARE_FILE"
else
    curl -L -o "$FIRMWARE_FILE" "$MICROPYTHON_URL"
    echo "   ✓ Downloaded: $FIRMWARE_FILE"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Hold the BOOTSEL button on your Pico W"
echo "   2. Plug in the USB cable (while holding BOOTSEL)"
echo "   3. Drag '$FIRMWARE_FILE' to the RPI-RP2 drive"
echo "   4. Wait for Pico W to reboot"
echo "   5. Run './deploy.sh' to upload your code"
echo ""
