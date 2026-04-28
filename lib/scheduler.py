# Scheduler with smooth transitions based on sunrise/sunset times

import time


class Scheduler:
    def __init__(self, storage, led_controller):
        """Initialize scheduler"""
        self.storage = storage
        self.led = led_controller
        self.sun_times = None  # Will be set by sun_times module (sunrise_time, sunset_time in seconds since midnight)
        self.current_step_index = None
        self.next_step_index = None
        self.transition_start = None
        self.transition_end = None
        self.last_valid_hsv = None  # Cache last valid color to maintain during transitions

    def set_sun_times(self, sunrise_seconds, sunset_seconds):
        """
        Set today's sunrise and sunset times
        sunrise_seconds: seconds since midnight (local time)
        sunset_seconds: seconds since midnight (local time)
        """
        self.sun_times = {
            "sunrise": sunrise_seconds,
            "sunset": sunset_seconds
        }
        print(f"Sun times updated: sunrise={sunrise_seconds}s, sunset={sunset_seconds}s")

    def _get_current_time_seconds(self):
        """Get current time as seconds since midnight (local time)"""
        # Note: This assumes the Pico's RTC is set to local time
        t = time.localtime()
        return t[3] * 3600 + t[4] * 60 + t[5]  # hours*3600 + minutes*60 + seconds

    def _calculate_step_time(self, step):
        """
        Calculate the absolute time (seconds since midnight) for a schedule step
        step: dict with either:
          - 'time': exact time in HH:MM format, OR
          - 'event' and 'offset': sun-based time
        Returns: seconds since midnight, or None if can't calculate
        """
        # Check for exact time first
        if "time" in step and step["time"]:
            try:
                time_str = step["time"]
                hours, minutes = map(int, time_str.split(':'))
                return hours * 3600 + minutes * 60
            except:
                pass

        # Fall back to sun-based time
        if self.sun_times is None:
            return None

        event = step.get("event", "sunset")
        offset_minutes = step.get("offset", 0)

        base_time = self.sun_times.get(event, self.sun_times["sunset"])
        return base_time + (offset_minutes * 60)

    def _get_sorted_steps(self):
        """
        Get schedule steps sorted by absolute time
        Returns: list of (time_seconds, step_dict) tuples
        """
        schedule = self.storage.get_schedule()
        timed_steps = []

        for step in schedule:
            step_time = self._calculate_step_time(step)
            if step_time is not None:
                timed_steps.append((step_time, step))

        # Sort by time
        timed_steps.sort(key=lambda x: x[0])
        return timed_steps

    def _find_current_and_next_steps(self, current_time):
        """
        Find the current and next schedule steps based on current time
        Returns: (current_step, next_step, current_time, next_time) or (None, None, None, None)
        """
        sorted_steps = self._get_sorted_steps()
        if not sorted_steps:
            return (None, None, None, None)

        # Find where we are in the schedule
        for i, (step_time, step) in enumerate(sorted_steps):
            if current_time < step_time:
                # We're before this step
                if i == 0:
                    # Before first step of the day - use last step from "yesterday"
                    prev_step = sorted_steps[-1][1]
                    prev_time = sorted_steps[-1][0] - 86400  # Subtract 24 hours
                else:
                    prev_step = sorted_steps[i - 1][1]
                    prev_time = sorted_steps[i - 1][0]

                return (prev_step, step, prev_time, step_time)

        # We're after all steps - transition to first step of "tomorrow"
        current_step = sorted_steps[-1][1]
        current_time_val = sorted_steps[-1][0]
        next_step = sorted_steps[0][1]
        next_time = sorted_steps[0][0] + 86400  # Add 24 hours

        return (current_step, next_step, current_time_val, next_time)

    def update(self):
        """
        Update scheduler - calculate current color based on schedule and transitions
        Call this regularly in the main loop
        """
        if self.sun_times is None:
            # Can't schedule without sun times - maintain last known color
            if self.last_valid_hsv:
                self.led.set_color_hsv(*self.last_valid_hsv)
            return

        current_time = self._get_current_time_seconds()
        current_step, next_step, current_time_val, next_time = self._find_current_and_next_steps(current_time)

        if current_step is None or next_step is None:
            # No valid schedule - maintain last known color
            if self.last_valid_hsv:
                self.led.set_color_hsv(*self.last_valid_hsv)
            return

        # Calculate transition progress
        time_into_transition = current_time - current_time_val
        total_transition_time = next_time - current_time_val

        if total_transition_time <= 0:
            # Avoid division by zero
            progress = 1.0
        else:
            progress = max(0.0, min(1.0, time_into_transition / total_transition_time))

        # Interpolate HSV values
        h1, s1, v1 = current_step["hue"], current_step["saturation"], current_step["brightness"]
        h2, s2, v2 = next_step["hue"], next_step["saturation"], next_step["brightness"]

        # Interpolate hue (handle wraparound for smooth color transitions)
        h_diff = h2 - h1
        if abs(h_diff) > 180:
            if h_diff > 0:
                h_diff -= 360
            else:
                h_diff += 360
        hue = (h1 + h_diff * progress) % 360

        # Linear interpolation for saturation and brightness
        saturation = s1 + (s2 - s1) * progress
        brightness = v1 + (v2 - v1) * progress

        # Cache this valid color
        self.last_valid_hsv = (hue, saturation, brightness)

        # Update LED
        self.led.set_color_hsv(hue, saturation, brightness)

    def get_current_schedule_info(self):
        """
        Get information about current position in schedule
        Returns: dict with current step, next step, progress, and upcoming events
        """
        if self.sun_times is None:
            return None

        current_time = self._get_current_time_seconds()
        current_step, next_step, current_time_val, next_time = self._find_current_and_next_steps(current_time)

        if current_step is None:
            return None

        time_into_transition = current_time - current_time_val
        total_transition_time = next_time - current_time_val
        progress = max(0.0, min(1.0, time_into_transition / total_transition_time)) if total_transition_time > 0 else 1.0

        # Get all upcoming events (sorted by time)
        sorted_steps = self._get_sorted_steps()
        upcoming = []
        for step_time, step in sorted_steps:
            if step_time > current_time:
                upcoming.append({
                    "step": step,
                    "time": step_time,
                    "seconds_until": int(step_time - current_time)
                })
            # Also check tomorrow's events
            elif step_time + 86400 > current_time:
                upcoming.append({
                    "step": step,
                    "time": step_time + 86400,
                    "seconds_until": int(step_time + 86400 - current_time)
                })

        # Sort by time
        upcoming.sort(key=lambda x: x["seconds_until"])

        return {
            "current_step": current_step,
            "next_step": next_step,
            "progress": progress,
            "next_event_in_seconds": int(next_time - current_time),
            "upcoming_events": upcoming[:5]  # Return next 5 events
        }
