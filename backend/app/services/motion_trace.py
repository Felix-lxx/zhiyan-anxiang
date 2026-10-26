"""Small, presentation-only history of positions actually reached by walkers.

Retain one preceding point for continuity; never predict motion or score from it.
"""
import math

TRACE_SECONDS = 4.
TRACE_POINTS = 18


def record_motion(actor, elapsed, position=None):
    point = {key: (position or actor).get(key, 0.) for key in ('x', 'y', 'height')}
    point['at_seconds'] = elapsed
    trace = actor.setdefault('motion_trace', [])
    if not trace or math.dist(tuple(trace[-1][k] for k in ('x', 'y', 'height')),
                              tuple(point[k] for k in ('x', 'y', 'height'))) > 1e-8:
        trace.append(point)
    # Keep the most recent stationary anchor; omit unchanged per-tick samples.
    while len(trace) > 2 and trace[1]['at_seconds'] < elapsed-TRACE_SECONDS:
        trace.pop(0)
    if len(trace) > TRACE_POINTS:
        del trace[:-TRACE_POINTS]
