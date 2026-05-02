#!/bin/bash
# Open a serial monitor to the Pico W.
# Exit screen with: Ctrl-A then k, then y.

set -e

BAUD="${BAUD:-115200}"

if [ -n "$1" ]; then
  PORT="$1"
else
  PORT=$(ls /dev/tty.usbmodem* 2>/dev/null | head -n1)
fi

if [ -z "$PORT" ] || [ ! -e "$PORT" ]; then
  echo "No Pico serial port found." >&2
  echo "Usage: $0 [/dev/tty.usbmodemXXXX]" >&2
  echo "Available ports:" >&2
  ls /dev/tty.usb* 2>/dev/null >&2 || echo "  (none)" >&2
  exit 1
fi

echo "Connecting to $PORT at $BAUD baud."
echo "Exit: Ctrl-A then k, then y."
echo

exec screen "$PORT" "$BAUD"
