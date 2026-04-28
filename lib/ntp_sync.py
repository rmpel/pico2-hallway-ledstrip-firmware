# NTP time synchronization
# Syncs Pico W RTC with internet time servers. RTC is always UTC; timezone
# offset for display/scheduling is handled separately by lib.tz_offset.

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
            NTP_DELTA = 2208988800  # Seconds between 1900 and 1970
            msg = b'\x1b' + 47 * b'\0'

            addr = socket.getaddrinfo(self.ntp_host, 123)[0][-1]
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(3)

            try:
                s.sendto(msg, addr)
                msg, address = s.recvfrom(1024)
            finally:
                s.close()

            val = struct.unpack("!I", msg[40:44])[0]
            return val - NTP_DELTA

        except Exception as e:
            print(f"NTP query failed: {e}")
            return None

    def sync_time(self, force=False):
        """
        Synchronize RTC with NTP (UTC).
        Returns: True if successful.
        """
        current_time = time.time()
        if not force and (current_time - self.last_sync_time) < self.sync_interval:
            return True

        print("Synchronizing time with NTP server (UTC)...")

        ntp_time = self._get_ntp_time()
        if ntp_time is None:
            print("Failed to get NTP time")
            return False

        # MicroPython time.localtime(epoch) interprets epoch as UTC and returns
        # a struct in UTC (no tz applied). RTC is then UTC.
        tm = time.localtime(ntp_time)
        rtc = machine.RTC()
        rtc.datetime((tm[0], tm[1], tm[2], tm[6], tm[3], tm[4], tm[5], 0))

        self.last_sync_time = time.time()
        print(f"Time synchronized (UTC): {tm[0]}-{tm[1]:02d}-{tm[2]:02d} {tm[3]:02d}:{tm[4]:02d}:{tm[5]:02d}")
        return True

    def should_sync(self):
        return (time.time() - self.last_sync_time) >= self.sync_interval

    def get_last_sync_time(self):
        if self.last_sync_time == 0:
            return None
        return time.time() - self.last_sync_time
