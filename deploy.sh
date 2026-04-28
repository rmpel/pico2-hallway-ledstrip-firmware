#!/bin/bash

# HallwayLedBar - Deploy script
# Copies all code to Pico W filesystem

set -e

echo "🚀 Deploying HallwayLedBar to Pico W"
echo "====================================="
echo ""

# Check if mpremote is installed
if ! command -v mpremote &> /dev/null; then
    echo "❌ mpremote not found. Run './install.sh' first."
    exit 1
fi

# Check if Pico W is connected
if ! mpremote connect list &> /dev/null; then
    echo "❌ Pico W not detected. Please connect your Pico W via USB."
    exit 1
fi

echo "✓ Pico W detected"
echo ""

echo "💡 TIP: If deployment fails, unplug/replug the Pico W and try again"
echo ""

# Create directories on Pico W
echo "📁 Creating directories..."
mpremote mkdir lib 2>/dev/null || true
mpremote mkdir web 2>/dev/null || true

# Copy library files
echo "📦 Copying library files..."
for file in lib/*.py; do
    if [ -f "$file" ]; then
        echo "   → $(basename $file)"
        mpremote cp "$file" ":$file"
    fi
done

# Copy web files
echo "🌐 Copying web files..."
for file in web/*; do
    if [ -f "$file" ]; then
        echo "   → $(basename $file)"
        mpremote cp "$file" ":$file"
    fi
done

# Copy main.py
echo "📄 Copying main.py..."
mpremote cp main.py :main.py

echo ""
echo "♻️  Resetting Pico W..."
mpremote reset

echo ""
echo "✅ Deployment complete!"
echo ""
echo "💡 Your Pico W is now running the updated code."
echo "   Connect to serial to see debug output:"
echo "   mpremote connect repl"
echo ""
