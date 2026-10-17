"""Versioned, read-only transport. Simulation ownership stays with the engine."""
from collections import OrderedDict
from threading import RLock
from concurrent.futures import Future
import json


def state_version(sequence: int, elapsed: int, presence_revision: int = 0) -> str:
    return f"{sequence}:{elapsed}:{presence_revision}"


def entity_patch(previous: list, current: list) -> dict | None:
    """ID-addressed field deltas preserve stable routes and unchanged actors."""
    def index(items):
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in items):
            return None
        mapped = {item["id"]: item for item in items}
        return mapped if len(mapped) == len(items) else None
    old, new = index(previous), index(current)
    if old is None or new is None:
        return None
    delta = {"added": [item for key, item in new.items() if key not in old],
             "removed": [key for key in old if key not in new], "updated": []}
    for key, item in new.items():
        if key not in old or item == old[key]:
            continue
        delta["updated"].append({"id": key, "set": {k: v for k, v in item.items() if k not in old[key] or old[key][k] != v},
                                 "unset": [k for k in old[key] if k not in item]})
    natural_order = [key for key in old if key in new] + [key for key in new if key not in old]
    if natural_order != list(new):
        delta["order"] = list(new)
    # Replacing a tiny/heavily changed collection can be cheaper than bookkeeping.
    if len(json.dumps(delta, ensure_ascii=False)) >= len(json.dumps(current, ensure_ascii=False)):
        return None
    return delta


def snapshot_patch(previous: dict, current: dict, path: list | None = None, *, entities: bool = False) -> list[dict]:
    """Protocol 1/2 retain array replacements; protocol 3 supports entity fields."""
    path = path or []
    changes = []
    for key in previous.keys() - current.keys():
        changes.append({"path": [*path, key], "remove": True})
    for key, value in current.items():
        location = [*path, key]
        if key not in previous:
            changes.append({"path": location, "value": value})
        elif isinstance(value, dict) and isinstance(previous[key], dict):
            changes.extend(snapshot_patch(previous[key], value, location, entities=entities))
        elif value != previous[key]:
            delta = entity_patch(previous[key], value) if entities and location in [
                ["simulation", "residents"], ["simulation", "helpers"], ["simulation", "vehicles"],
                ["simulation", "rescue_actions"],
            ] and isinstance(previous[key], list) and isinstance(value, list) else None
            changes.append({"path": location, **({"entities": delta} if delta is not None else {"value": value})})
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
