"""Bounded, disposable acceleration state. Events and frozen inputs remain authoritative."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
import json
from threading import RLock

ENGINE_REVISION = 4
_states = OrderedDict()
_lock = RLock()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def recall(world, elapsed):
    key = digest(world)
    with _lock:
        state = _states.get(key)
        if state and state["now"] <= elapsed:
            _states.move_to_end(key)
            return deepcopy(state)
    return None


def remember(world, state):
    if not state:
        return
    key = digest(world)
    with _lock:
        if key not in _states or _states[key]["now"] <= state["now"]:
            _states[key] = deepcopy(state)
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
