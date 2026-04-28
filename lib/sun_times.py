# Sunrise/sunset times API client with caching

import urequests
import time
from config import SUN_TIMES_API, SUN_TIMES_CACHE_HOURS


class SunTimes:
    def __init__(self, storage):
        """Initialize sun times client"""
        self.storage = storage
        self.cached_sunrise = None
        self.cached_sunset = None
        self.cache_timestamp = 0

    def _parse_time_to_seconds(self, time_str):
        """
        Parse time string to seconds since midnight
        time_str: format "HH:MM:SS AM/PM"
        Returns: seconds since midnight
        """
        try:
            time_parts = time_str.split()
            time_components = time_parts[0].split(":")
            hours = int(time_components[0])
            minutes = int(time_components[1])
            seconds = int(time_components[2])

            # Handle AM/PM
            if len(time_parts) > 1:
                am_pm = time_parts[1]
                if am_pm == "PM" and hours != 12:
                    hours += 12
                elif am_pm == "AM" and hours == 12:
                    hours = 0

            return hours * 3600 + minutes * 60 + seconds
        except Exception as e:
            print(f"Error parsing time '{time_str}': {e}")
            return None

    def _fetch_from_api(self):
        """
        Fetch sunrise/sunset times from API
        Returns: (sunrise_seconds, sunset_seconds) or (None, None)
        """
        lat, lon = self.storage.get_location()

        if lat is None or lon is None:
            print("Location not configured, cannot fetch sun times")
            return (None, None)

        try:
            url = f"{SUN_TIMES_API}?lat={lat}&lng={lon}&formatted=1"
            print(f"Fetching sun times from: {url}")

            response = urequests.get(url)
            data = response.json()
            response.close()

            if data.get("status") != "OK":
                print(f"API error: {data}")
                return (None, None)

            results = data.get("results", {})
            sunrise_str = results.get("sunrise")
            sunset_str = results.get("sunset")

            if not sunrise_str or not sunset_str:
                print("Missing sunrise/sunset in API response")
                return (None, None)

            sunrise_seconds = self._parse_time_to_seconds(sunrise_str)
            sunset_seconds = self._parse_time_to_seconds(sunset_str)

            print(f"Fetched sun times: sunrise={sunrise_str} ({sunrise_seconds}s), sunset={sunset_str} ({sunset_seconds}s)")

            return (sunrise_seconds, sunset_seconds)

        except Exception as e:
            print(f"Failed to fetch sun times: {e}")
            return (None, None)

    def get_sun_times(self, force_refresh=False):
        """
        Get sunrise and sunset times (cached or fresh)
        force_refresh: Force refresh from API
        Returns: (sunrise_seconds, sunset_seconds) or (None, None)
        """
        now = time.time()
        cache_age_hours = (now - self.cache_timestamp) / 3600

        # Check if cache is valid
        if not force_refresh and cache_age_hours < SUN_TIMES_CACHE_HOURS and self.cached_sunrise is not None:
            print(f"Using cached sun times (age: {cache_age_hours:.1f}h)")
            return (self.cached_sunrise, self.cached_sunset)

        # Fetch fresh data
        sunrise, sunset = self._fetch_from_api()

        if sunrise is not None and sunset is not None:
            # Update cache
            self.cached_sunrise = sunrise
            self.cached_sunset = sunset
            self.cache_timestamp = now

        return (sunrise, sunset)

    def update_scheduler(self, scheduler, force_refresh=False):
        """
        Update scheduler with current sun times
        scheduler: Scheduler instance
        force_refresh: Force refresh from API
        Returns: True if successful, False otherwise
        """
        sunrise, sunset = self.get_sun_times(force_refresh)

        if sunrise is not None and sunset is not None:
            scheduler.set_sun_times(sunrise, sunset)
            return True

        return False
