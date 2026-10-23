"""Process-local serialization for the SQLite development transaction boundary."""
from functools import wraps
from inspect import signature
from threading import RLock

_command_lock = RLock()


def serialized_command(function):
    # Reentrant: the workflow and command application may call the same handler.
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _command_lock:
            return function(*args, **kwargs)
    # Resolve postponed annotations in the decorated function's own module.
    # FastAPI otherwise resolves route types against this lock module after
    # extraction and may interpret model parameters as ordinary query fields.
    wrapped.__signature__ = signature(function, eval_str=True)
    return wrapped
