# NTP time synchronization
# Syncs Pico W RTC with internet time servers

import socket
import struct
import time
import machine


class NTPSync:
    def __init__(self, storage):
        """Initialize NTP sync"""
        self.storage = storage
        self.last_sync_time = 0
        self.sync_interval = 3600  # Sync every hour
        self.ntp_host = "pool.ntp.org"

    def _get_ntp_time(self):
        """
        Query NTP server and get current time
        Returns: seconds since epoch (1970-01-01) or None on failure
        """
        try:
            # NTP packet format
            NTP_DELTA = 2208988800  # Seconds between 1900 and 1970

            # Create NTP request packet
            msg = b'\x1b' + 47 * b'\0'

            # Send request
            addr = socket.getaddrinfo(self.ntp_host, 123)[0][-1]
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)

            try:
                s.sendto(msg, addr)
                msg, address = s.recvfrom(1024)
            finally:
                s.close()

            # Extract timestamp (bytes 40-43)
            val = struct.unpack("!I", msg[40:44])[0]

            # Convert to seconds since 1970
            ntp_time = val - NTP_DELTA

            return ntp_time

        except Exception as e:
            print(f"NTP query failed: {e}")
            return None

    def _get_timezone_offset_from_api(self, utc_timestamp):
        """
        Get timezone offset (including DST) from worldtimeapi.org
        Returns: offset in seconds, or None on failure
        """
        try:
            # get_location() returns (lat, lon, timezone)
            lat, lon, timezone = self.storage.get_location()

            # Use worldtimeapi.org to get current timezone info with DST
            url = f"http://worldtimeapi.org/api/timezone/{timezone}"

            import urequests
            response = urequests.get(url, timeout=5)
            data = response.json()
            response.close()

            # Extract timezone offset in seconds
            # raw_offset is base offset, dst_offset is DST adjustment
            raw_offset = data.get("raw_offset", 0)
            dst_offset = data.get("dst_offset", 0)
            total_offset = raw_offset + dst_offset

            print(f"Timezone {timezone}: offset={total_offset}s (base={raw_offset}, DST={dst_offset})")

            return total_offset

        except Exception as e:
            print(f"Failed to get timezone offset from API: {e}")
            return None

    def _apply_timezone_offset(self, utc_timestamp):
        """
        Apply timezone offset to UTC timestamp
        Returns: local timestamp
        """
        # Try to get offset from API (includes DST)
        offset = self._get_timezone_offset_from_api(utc_timestamp)

        if offset is not None:
            return utc_timestamp + offset

        # Fallback to simple fixed offsets
        # get_location() returns (lat, lon, timezone)
        lat, lon, timezone = self.storage.get_location()

        timezone_offsets = {
            "UTC": 0,
            "Europe/Amsterdam": 1 * 3600,  # CET (winter) - simplified
            "Europe/London": 0,
            "America/New_York": -5 * 3600,
            "America/Los_Angeles": -8 * 3600,
            "Asia/Tokyo": 9 * 3600,
        }

        offset_seconds = timezone_offsets.get(timezone, 0)
        print(f"Using fallback timezone offset for {timezone}: {offset_seconds}s")

        return utc_timestamp + offset_seconds

    def sync_time(self, force=False):
        """
        Synchronize RTC with NTP server
        force: Force sync even if recently synced
        Returns: True if successful, False otherwise
        """
        current_time = time.time()

        # Check if we need to sync
        if not force and (current_time - self.last_sync_time) < self.sync_interval:
            return True  # Recently synced, no need to sync again

        print("Synchronizing time with NTP server...")

        # Get NTP time
        ntp_time = self._get_ntp_time()
        if ntp_time is None:
            print("Failed to get NTP time")
            return False

        # Apply timezone offset
        local_time = self._apply_timezone_offset(ntp_time)

        # Set RTC
        tm = time.localtime(local_time)
        rtc = machine.RTC()

        # RTC expects: (year, month, day, weekday, hours, minutes, seconds, subseconds)
        rtc.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))

        self.last_sync_time = time.time()

        print(f"Time synchronized: {tm[0]}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}")

        return True

    def should_sync(self):
        """
        Check if time sync is needed
        Returns: True if sync needed, False otherwise
        """
        current_time = time.time()
        return (current_time - self.last_sync_time) >= self.sync_interval

    def get_last_sync_time(self):
        """
        Get time of last successful sync
        Returns: seconds since last sync, or None if never synced
        """
        if self.last_sync_time == 0:
            return None
        return time.time() - self.last_sync_time
