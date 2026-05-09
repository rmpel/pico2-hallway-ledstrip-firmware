# Shared game infrastructure used by Simon Says and Master Mind.
#
# Snake (lib/game.py) predates this module and deliberately does NOT inherit
# from BaseGame — see §0 / §3 of todo-more-games.md. The helpers here are
# light-touch: a settings reader, a dual-meaning count helper, generic JSON
# highscore I/O, the BaseGame abstract, and a small registry that lets each
# game refuse-if-busy when another is already running.

import json
import time
import _thread


# Canonical hardware button names. Single source of truth shared by every
# place that maps an action to a physical button.
BUTTON_NAMES = ("off", "auto", "on", "f1", "f2", "alt")


def load_game_overrides(slot):
    """Read /settings.json and return its top-level <slot> dict (e.g. "game2",
    "game3"), or {} on any error / missing key. Caller falls back to its own
    defaults for missing entries."""
    try:
        with open("/settings.json", "r") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    sub = data.get(slot)
    return sub if isinstance(sub, dict) else {}


def resolve_count(value, total):
    """Dual-meaning helper. value < 1 → fraction of total; value >= 1 →
    exact (integer) count. Used by all three games for things like start
    length, shield offset, and so on."""
    if value < 1:
        return int(total * value)
    return int(value)


def load_highscore_dict(path, default):
    """Load a dict-shaped highscore file. Returns `default` on any error.
    The default is shallow-copied so callers can't accidentally mutate the
    one we hand back to the next call."""
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return dict(default)


def save_highscore_dict(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError as e:
        print("game_common: highscore save failed:", path, e)


def resolve_button_map(raw, action_to_color, defaults):
    """Resolve a {action_name -> button_name} settings dict to a runtime
    {button_name -> color_letter} map. `action_to_color` maps action keys
    (e.g. "input_red") to color letters ("R"); `defaults` is the same shape
    as the resolved output and is used for any action the user did not
    override.

    Buttons that end up with no assigned color (because the user reassigned
    that color elsewhere and didn't replace this one) are dropped — those
    presses become no-ops in-game rather than firing a stale color."""
    result = dict(defaults)
    if not isinstance(raw, dict):
        return result

    overlay = {}
    for action, btn in raw.items():
        color = action_to_color.get(action)
        if color is None or btn not in BUTTON_NAMES:
            continue
        overlay[btn] = color
    if not overlay:
        return result

    used_colors = set(overlay.values())
    for btn in list(result):
        if btn in overlay:
            continue
        if result[btn] in used_colors:
            del result[btn]
    result.update(overlay)
    return result


class GameRegistry:
    """Tracks all games so each can refuse-if-busy when another is active.
    The registry is a plain list; we don't expect more than a handful of
    games and a linear scan is fine."""

    def __init__(self):
        self._games = []

    def register(self, *games):
        for g in games:
            if g is not None and g not in self._games:
                self._games.append(g)

    def any_active(self):
        for g in self._games:
            if g.is_active():
                return True
        return False

    def current_active(self):
        for g in self._games:
            if g.is_active():
                return g
        return None

    def others_active(self, self_game):
        for g in self._games:
            if g is self_game:
                continue
            if g.is_active():
                return True
        return False


class BaseGame:
    """Minimal base for new games. Owns the cross-thread plumbing that all
    games need (a lock + pending start/stop queues), an on_active_change
    callback, and a tick() that delegates to subclass hooks. Subclasses
    must implement _drain_pending_inputs / _advance_state / _render and
    supply their own state machine.

    Snake does NOT inherit from this. The interface here is intentionally
    not a strict "Game" contract — it's just what Simon and Master Mind
    actually need."""

    def __init__(self, led, storage, registry):
        self.led = led
        self.storage = storage
        self.registry = registry
        if registry is not None:
            registry.register(self)

        # Cross-thread coordination
        self._lock = _thread.allocate_lock()
        self._pending_start = False
        self._pending_stop = False

        # Public callback (set by main): on_active_change(active: bool)
        self.on_active_change = None

        # State string. Subclass-defined values; "inactive" is the only one
        # this base class cares about.
        self.state = "inactive"

    # ---------- public API ----------

    def is_active(self):
        return self.state != "inactive"

    def start(self):
        """Queue a start request. The actual transition happens on the next
        tick() (core 0). Refused silently if another game is active — the
        request is still queued but the registry check in _try_begin will
        drop it."""
        with self._lock:
            self._pending_start = True

    def stop(self):
        with self._lock:
            self._pending_stop = True

    def tick(self):
        now = time.ticks_ms()
        self._drain_pending_inputs(now)
        if self.state == "inactive":
            return
        self._advance_state(now)
        self._render()

    # ---------- subclass hooks ----------

    def _drain_pending_inputs(self, now):
        raise NotImplementedError

    def _advance_state(self, now):
        raise NotImplementedError

    def _render(self):
        raise NotImplementedError

    # ---------- helpers for subclasses ----------

    def _set_state(self, new_state):
        was_active = self.state != "inactive"
        self.state = new_state
        is_active = new_state != "inactive"
        if was_active != is_active and self.on_active_change is not None:
            try:
                self.on_active_change(is_active)
            except Exception as e:
                print("base_game: on_active_change error:", e)

    def _try_begin(self):
        """Subclass calls this when it sees a pending_start. Returns True if
        this game may take the strip (no other game is active); False to
        refuse. The web layer surfaces a 409 by checking registry separately
        before forwarding the start."""
        if self.registry is not None and self.registry.others_active(self):
            return False
        return True
