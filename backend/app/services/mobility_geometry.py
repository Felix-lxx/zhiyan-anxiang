"""Physical envelopes shared by route validation and derived vehicle poses."""
import math


VEHICLE_LENGTHS = {"firetruck": 6.2, "ambulance": 5.2}


def half_length(actor):
    # A stretcher is an explicitly different mobility profile, not a narrow truck.
    if actor.get("kind") == "stretcher":
        return 2.0
    return VEHICLE_LENGTHS.get(actor.get("kind"), 6.2) / 2


def heading_between(start, end):
    """Yaw in the renderer's -Z-forward convention, using frozen X/Y axes."""
    dx, dy = end["x"] - start["x"], end["y"] - start["y"]
    return math.atan2(-dx, -dy) if math.hypot(dx, dy) > 1e-8 else None
