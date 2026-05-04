#!/usr/bin/env bash
# flash.sh HOST COLOR COUNT DURATION_MS
#   HOST         e.g. 192.168.41.14
#   COLOR        R,G,B (0-255 each) or hex (RRGGBB / #RRGGBB / FFF / #FFF)
#   COUNT        number of on-flashes
#   DURATION_MS  on-time = off-time in milliseconds
#
# Drives /api/preview (HSV) for the on/off cycle, then /api/preview/stop
# to hand control back to whatever mode was running.
#
# All curl calls are fire-and-forget (non-blocking) so request latency
# does not skew the flash cadence.

set -u

if [ "$#" -ne 4 ]; then
    echo "Usage: $0 HOST COLOR COUNT DURATION_MS" >&2
    echo "  COLOR: R,G,B (0-255) or hex RRGGBB / #RRGGBB / RGB / #RGB" >&2
    exit 1
fi

HOST="$1"
COLOR_RAW="$2"
COUNT="$3"
DURATION_MS="$4"

# --- parse color -> R G B (0-255) --------------------------------------------
parse_color() {
    local in="$1"
    if [[ "$in" == *,* ]]; then
        IFS=',' read -r R G B <<< "$in"
    else
        local hex="${in#'#'}"
        case "${#hex}" in
            3) hex="${hex:0:1}${hex:0:1}${hex:1:1}${hex:1:1}${hex:2:1}${hex:2:1}" ;;
            6) ;;
            *) echo "Invalid hex color: $in" >&2; exit 1 ;;
        esac
        if ! [[ "$hex" =~ ^[0-9A-Fa-f]{6}$ ]]; then
            echo "Invalid hex color: $in" >&2; exit 1
        fi
        R=$((16#${hex:0:2}))
        G=$((16#${hex:2:2}))
        B=$((16#${hex:4:2}))
    fi
    for v in "$R" "$G" "$B"; do
        if ! [[ "$v" =~ ^[0-9]+$ ]] || [ "$v" -lt 0 ] || [ "$v" -gt 255 ]; then
            echo "Invalid color component: $v" >&2; exit 1
        fi
    done
}

parse_color "$COLOR_RAW"

# --- RGB -> HSV (hue 0-360, sat 0-100, val 0-100) ----------------------------
read HUE SAT VAL <<< "$(awk -v r="$R" -v g="$G" -v b="$B" 'BEGIN{
    rf=r/255; gf=g/255; bf=b/255;
    mx=rf; if(gf>mx)mx=gf; if(bf>mx)mx=bf;
    mn=rf; if(gf<mn)mn=gf; if(bf<mn)mn=bf;
    d=mx-mn;
    h=0;
    if(d>0){
        if(mx==rf){ h=60*(((gf-bf)/d) % 6); }
        else if(mx==gf){ h=60*(((bf-rf)/d)+2); }
        else { h=60*(((rf-gf)/d)+4); }
    }
    if(h<0) h+=360;
    s=(mx==0)?0:(d/mx)*100;
    v=mx*100;
    printf "%d %d %d", int(h+0.5), int(s+0.5), int(v+0.5);
}')"

if ! [[ "$COUNT" =~ ^[0-9]+$ ]] || [ "$COUNT" -lt 1 ]; then
    echo "COUNT must be a positive integer" >&2; exit 1
fi
if ! [[ "$DURATION_MS" =~ ^[0-9]+$ ]] || [ "$DURATION_MS" -lt 1 ]; then
    echo "DURATION_MS must be a positive integer" >&2; exit 1
fi

# bash `sleep` accepts fractional seconds
SLEEP_SEC="$(awk -v ms="$DURATION_MS" 'BEGIN{printf "%.3f", ms/1000}')"

ON_BODY="{\"hue\":${HUE},\"saturation\":${SAT},\"brightness\":${VAL}}"
OFF_BODY="{\"hue\":${HUE},\"saturation\":${SAT},\"brightness\":0}"

post() {
    # fire-and-forget; short connect timeout, discard output
    curl -s -o /dev/null --connect-timeout 1 --max-time 2 \
        -X POST -H 'Content-Type: application/json' \
        -d "$2" "http://${HOST}$1"
}

for ((i=0; i<COUNT; i++)); do
    post /api/preview "$ON_BODY"
    sleep "$SLEEP_SEC"
    post /api/preview "$OFF_BODY"
    sleep "$SLEEP_SEC"
done

# resume the device's prior operating mode
post /api/preview/stop ''

# wait for backgrounded curls to settle so the script exits cleanly
wait 2>/dev/null
