"""Bounded, disposable acceleration state. Events and frozen inputs remain authoritative."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock

ENGINE_REVISION = 9
_states = OrderedDict()
_lock = RLock()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def recall(world, elapsed):
    key = digest(world)
    with _lock:
        candidates = _states.get(key, [])
        state = max((s for s in candidates if s["now"] <= elapsed), key=lambda s: s["now"], default=None)
        if state:
            _states.move_to_end(key)
            return deepcopy(state)
    return None


def remember(world, state):
    if not state:
        return
    key = digest(world)
    with _lock:
        # Forecasts at t+30 must not replace the only live checkpoint at t.
        candidates = [s for s in _states.get(key, []) if s["now"] != state["now"]]
        candidates.append(deepcopy(state))
        _states[key] = sorted(candidates, key=lambda s: s["now"])[-8:]
        _states.move_to_end(key)
        while len(_states) > 16:
            _states.popitem(last=False)


def simulate_incrementally(world, events, elapsed, strategy=None, branch_at=None):
    from app.services.spatial_simulation import simulate
    if strategy:
        return simulate(world, events, elapsed, strategy, branch_at)
    checkpoint = recall(world, elapsed)
    saved = {}
    result = simulate(world, events, elapsed, checkpoint=checkpoint, checkpoint_out=saved)
    remember(world, saved)
    return result
