# Timezone offset resolution from geo coordinates.
# Uses timeapi.io which returns the current UTC offset (incl. DST) for a
# lat/lon pair. The result is cached on the device — refreshed weekly so
# DST transitions are picked up within a week.

import gc
import time
try:
    import urequests
except ImportError:
    urequests = None
from config import HTTP_PROXY


TIMEAPI_URL = "https://www.timeapi.io/api/timezone/coordinate"
REFRESH_INTERVAL_SECONDS = 7 * 24 * 3600  # weekly


_HEX = "0123456789ABCDEF"


def _url_encode(s):
    out = []
    for ch in s:
        if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "-_.~":
            out.append(ch)
        else:
            for b in ch.encode("utf-8"):
                out.append("%")
                out.append(_HEX[(b >> 4) & 0xF])
                out.append(_HEX[b & 0xF])
    return "".join(out)


def _maybe_proxy(url):
    # HTTP_PROXY is the bare proxy hostname; firmware builds the full URL.
    # Empty / missing → direct HTTPS.
    if not HTTP_PROXY:
        return url
    return "http://" + HTTP_PROXY + "/?_=" + _url_encode(url)


class TzOffset:
    def __init__(self, storage):
        self.storage = storage

    def get_cached_offset(self):
        """Returns stored offset seconds (0 if none)."""
        return self.storage.get_tz_offset_seconds()

    def needs_refresh(self):
        last = self.storage.get_tz_offset_updated()
        if last is None or last == 0:
            return True
        return (time.time() - last) >= REFRESH_INTERVAL_SECONDS

    def refresh(self, force=False):
        """
        Fetch current UTC offset for the device's coordinates and cache it.
        Returns offset seconds on success, None on failure.
        """
        if not force and not self.needs_refresh():
            return self.get_cached_offset()

        if urequests is None:
            print("urequests unavailable; cannot refresh tz offset")
            return None

        if not self.storage.has_location_config():
            print("No location configured; tz offset stays cached")
            return None

        lat, lon = self.storage.get_location()[0], self.storage.get_location()[1]
        upstream = f"{TIMEAPI_URL}?latitude={lat}&longitude={lon}"
        url = _maybe_proxy(upstream)
        try:
            print(f"Fetching tz offset from {url}")
            gc.collect()
            r = urequests.get(url)
            data = r.json()
            r.close()
            r = None
            gc.collect()
        except Exception as e:
            print(f"tz offset fetch failed: {e}")
            return None

        offset = None
        cur = data.get("currentUtcOffset") if isinstance(data, dict) else None
        if isinstance(cur, dict) and "seconds" in cur:
            offset = int(cur["seconds"])
        else:
            # Fallback: parse "+02:00" / "-05:30" string fields if present
            s = data.get("currentUtcOffset") if isinstance(data, dict) else None
            if isinstance(s, str):
                offset = _parse_offset_string(s)

        if offset is None:
            print(f"Could not parse tz offset from response: {data}")
            return None

        self.storage.set_tz_offset(offset, int(time.time()))
        print(f"tz offset cached: {offset}s")
        return offset


def _parse_offset_string(s):
    try:
        sign = 1
        if s[0] in ("+", "-"):
            if s[0] == "-":
                sign = -1
            s = s[1:]
        h, m = s.split(":")
        return sign * (int(h) * 3600 + int(m) * 60)
    except Exception:
        return None
