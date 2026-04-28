#!/bin/bash

# HallwayLedBar - Wireless deploy script
# Pushes all code to a running Pico W over Wi-Fi using ./picp.
# Usage: ./deploy-wireless.sh <host> [--reboot]
#   host:     IP address or hostname of the Pico W (e.g. hallway.local)
#   --reboot: reboot the device after upload (needed when Python files change)

set -e

REBOOT=0
HOST=""
for arg in "$@"; do
    case "$arg" in
        --reboot) REBOOT=1 ;;
        -h|--help)
            echo "Usage: $0 <host> [--reboot]"
            echo "  host:     IP address or hostname of the Pico W (e.g. hallway.local)"
            echo "  --reboot: reboot the device after upload (needed when Python files change)"
            exit 0 ;;
        -*)
            echo "Unknown option: $arg" >&2
            exit 1 ;;
        *)
            if [ -z "$HOST" ]; then HOST="$arg"
            else echo "Unexpected argument: $arg" >&2; exit 1
            fi ;;
    esac
done

if [ -z "$HOST" ]; then
    echo "Usage: $0 <host> [--reboot]"
    echo "  host:     IP address or hostname of the Pico W (e.g. hallway.local)"
    echo "  --reboot: reboot the device after upload (needed when Python files change)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PICP="$SCRIPT_DIR/picp"

echo "🚀 Deploying HallwayLedBar to ${HOST}"
echo "====================================="
echo ""

if [ ! -x "$PICP" ]; then
    echo "❌ picp not found or not executable at: $PICP"
    exit 1
fi

# Quick reachability check — the device must already be on Wi-Fi running the
# updated web server with the /api/files/upload endpoint.
if ! curl -sSf -o /dev/null --max-time 5 "http://${HOST}/api/status"; then
    echo "❌ Could not reach http://${HOST}/api/status"
    echo "   Make sure the device is powered on and connected to Wi-Fi."
    exit 1
fi
echo "✓ Device reachable at http://${HOST}/"
echo ""

echo "💡 TIP: If a single file fails, you can re-push it with:"
echo "        ./picp -h ${HOST} <local> <remote>"
echo ""

push() {
    local local_file="$1"
    local remote_path="$2"
    echo "   → ${remote_path}"
    "$PICP" -h "$HOST" "$local_file" "$remote_path" >/dev/null
}

cd "$SCRIPT_DIR"

echo "📦 Copying library files..."
for file in lib/*.py; do
    if [ -f "$file" ]; then
        push "$file" "$file"
    fi
done

echo "🌐 Copying web files..."
for file in web/*; do
    if [ -f "$file" ]; then
        push "$file" "$file"
    fi
done

echo "📄 Copying main.py..."
push main.py main.py

echo ""
if [ "$REBOOT" -eq 1 ]; then
    echo "♻️  Rebooting device..."
    curl -sS -X POST "http://${HOST}/api/reboot" >/dev/null || true
    echo ""
    echo "✅ Deployment complete!"
    echo ""
    echo "💡 Device is rebooting; give it a few seconds before reconnecting."
else
    echo "✅ Deployment complete!"
    echo ""
    echo "💡 Pass --reboot to restart the device (required if you changed Python files)."
fi
echo "   Status: http://${HOST}/"
echo ""
