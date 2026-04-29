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
        # Baseline for step-boundary detection (used by auto-resume from manual modes).
        # None = not primed yet; otherwise = last-seen current_time_val % 86400.
        self._step_baseline = None

    def set_sun_times(self, sunrise_seconds, sunset_seconds):
        """
        Set today's sunrise and sunset times.
        Values are seconds since UTC midnight (as returned by sunrise-sunset.org
        without a tzid). They get converted to local seconds-since-midnight at
        compare time using the cached tz offset.
        """
        self.sun_times = {
            "sunrise_utc": sunrise_seconds,
            "sunset_utc": sunset_seconds
        }
        print(f"Sun times updated (UTC): sunrise={sunrise_seconds}s, sunset={sunset_seconds}s")

    def _tz_offset(self):
        return self.storage.get_tz_offset_seconds()

    def _get_current_time_seconds(self):
        """Seconds-since-local-midnight, derived from UTC RTC + cached tz offset."""
        local_epoch = time.time() + self._tz_offset()
        return int(local_epoch % 86400)

    def _sun_to_local_seconds(self, utc_seconds_since_midnight):
        """Convert sunrise/sunset (UTC seconds since midnight) -> local seconds since midnight."""
        return (utc_seconds_since_midnight + self._tz_offset()) % 86400

    def _sun_times_local(self):
        if self.sun_times is None:
            return None
        return {
            "sunrise": self._sun_to_local_seconds(self.sun_times["sunrise_utc"]),
            "sunset": self._sun_to_local_seconds(self.sun_times["sunset_utc"])
        }

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

        # Fall back to sun-based time (convert stored UTC sun times to local)
        local = self._sun_times_local()
        if local is None:
            return None

        event = step.get("event", "sunset")
        offset_minutes = step.get("offset", 0)
        base_time = local.get(event, local["sunset"])
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

    def _current_step_key(self):
        """Return a stable key for the active schedule step, or None if unknown."""
        if self.sun_times is None:
            return None
        current_time = self._get_current_time_seconds()
        _, _, current_time_val, _ = self._find_current_and_next_steps(current_time)
        if current_time_val is None:
            return None
        # Normalize so 'yesterday's last step' (negative) compares equal to today's.
        return current_time_val % 86400

    def prime_step_baseline(self):
        """Snapshot the active step. Subsequent step_changed_since_baseline()
        calls return False until the active step rolls over."""
        self._step_baseline = self._current_step_key()

    def step_changed_since_baseline(self):
        """True if the active step differs from the one captured by prime_step_baseline().
        Returns False if the baseline isn't set or the schedule isn't ready."""
        if self._step_baseline is None:
            return False
        key = self._current_step_key()
        if key is None:
            return False
        return key != self._step_baseline

    def get_current_schedule_info(self):
        """
        Get information about current position in schedule.
        Returns dict with:
          - current_step / next_step / progress / next_event_in_seconds (legacy)
          - steps: full list, sorted current-first then by ascending seconds_until.
                   Each entry has step, time, seconds_until, is_current.
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

        sorted_steps = self._get_sorted_steps()

        # Build full list. Each step's "next occurrence" is today if still
        # ahead, else tomorrow. The current step is the one whose most-recent
        # occurrence is current_time_val (could be today or yesterday).
        steps_out = []
        for step_time, step in sorted_steps:
            is_current = (step is current_step)
            if is_current:
                # Use the (possibly negative) current_time_val so the UI can
                # show "current" without it being mis-sorted as "tomorrow".
                t = current_time_val
                secs_until = int(t - current_time)  # <= 0
            elif step_time > current_time:
                t = step_time
                secs_until = int(step_time - current_time)
            else:
                t = step_time + 86400
                secs_until = int(step_time + 86400 - current_time)
            steps_out.append({
                "step": step,
                "time": t,
                "seconds_until": secs_until,
                "is_current": is_current
            })

        # Sort: current first (its seconds_until is <= 0), then ascending.
        steps_out.sort(key=lambda x: (0 if x["is_current"] else 1, x["seconds_until"]))

        # Legacy upcoming list (kept for any consumer that still uses it).
        upcoming = [s for s in steps_out if not s["is_current"]][:5]

        return {
            "current_step": current_step,
            "next_step": next_step,
            "progress": progress,
            "next_event_in_seconds": int(next_time - current_time),
            "upcoming_events": upcoming,
            "steps": steps_out
        }
