"""Escort contact and bounded trailing positions on the walked route."""
import math


def position(actor):
    return tuple(actor.get(key, 0.) for key in ('x', 'y', 'height'))


def can_meet(helper, resident, edges):
    if math.dist(position(helper), position(resident)) > .85:
        return False
    a, b = helper.get('edge_id'), resident.get('edge_id')
    if a and b:
        return a == b
    if not a and not b:
        return helper['node_id'] == resident['node_id']
    occupied, waiting = (helper, resident) if a else (resident, helper)
    edge = edges[occupied['edge_id']]
    return waiting['node_id'] in (edge['start_node_id'], edge['end_node_id'])


def follow_walked_path(helper, resident, spacing=.7):
    # Store only the short tail actually walked, including turns and stairs.
    # Never offset in world X: that puts helpers through narrow corridor walls.
    trail = helper.setdefault('escort_trail', [position(helper)])
    target = position(resident)
    if math.dist(trail[-1], target) > 1e-8:
        trail.append(target)
    length = sum(math.dist(a, b) for a, b in zip(trail, trail[1:]))
    remaining = max(0., length-spacing)
    while len(trail) > 1 and remaining > 1e-8:
        segment = math.dist(trail[0], trail[1])
        if segment <= remaining+1e-8:
            remaining -= segment
            trail.pop(0)
        else:
            ratio = remaining/segment
            trail[0] = tuple(a+(b-a)*ratio for a,b in zip(trail[0],trail[1]))
            remaining = 0.
    for key, value in zip(('x','y','height'),trail[0]):
        helper[key] = value
