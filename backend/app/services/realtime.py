"""Versioned, read-only transport. Simulation ownership stays with the engine."""
from collections import OrderedDict
from threading import RLock
from concurrent.futures import Future


def state_version(sequence: int, elapsed: int, presence_revision: int = 0) -> str:
    return f"{sequence}:{elapsed}:{presence_revision}"


def snapshot_patch(previous: dict, current: dict, path: list | None = None) -> list[dict]:
    """Recursive object replacements; arrays are atomic to preserve actor ordering."""
    path = path or []
    changes = []
    for key in previous.keys() - current.keys():
        changes.append({"path": [*path, key], "remove": True})
    for key, value in current.items():
        location = [*path, key]
        if key not in previous:
            changes.append({"path": location, "value": value})
        elif isinstance(value, dict) and isinstance(previous[key], dict):
            changes.extend(snapshot_patch(previous[key], value, location))
        elif value != previous[key]:
            changes.append({"path": location, "value": value})
    return changes


class SnapshotCache:
    """Bounded per-process cache: clients observing the same tick share its result."""

    def __init__(self, capacity: int = 32):
        self.capacity = capacity
        self._entries = OrderedDict()
        self._lock = RLock()
        self._pending = {}

    def get(self, drill_id, version, factory):
        key = (drill_id, version)
        with self._lock:
            found = self._entries.get(drill_id)
            if found and found[0] == version:
                self._entries.move_to_end(drill_id)
                return found[1]
            pending = self._pending.get(key)
            owner = pending is None
            if owner:
                pending = self._pending[key] = Future()
        if not owner:
            return pending.result()
        try:
            # Expensive simulation never holds the global cache mutex. Unrelated
            # drills can progress concurrently; same-version observers share work.
            result = factory()
            with self._lock:
                self._entries[drill_id] = (result["state_version"], result)
                self._entries.move_to_end(drill_id)
                while len(self._entries) > self.capacity:
                    self._entries.popitem(last=False)
            pending.set_result(result)
            return result
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)


live_snapshots = SnapshotCache()
