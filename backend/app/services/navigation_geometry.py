"""Shared plan-time building geometry in frozen scene coordinates."""
import heapq
import math


def building_obstacles(world):
    return [{key: obj[key] for key in ("x", "y", "width", "depth")}
            for obj in world.get("objects", []) if obj.get("type") == "building"]


def clear_segment(start, end, obstacles, clearance=0.):
    """Test the whole segment against expanded footprints, not just its endpoints."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    for box in obstacles:
        lo, hi = 0., 1.
        left, right = box["x"] - box["width"] / 2 - clearance, box["x"] + box["width"] / 2 + clearance
        top, bottom = box["y"] - box["depth"] / 2 - clearance, box["y"] + box["depth"] / 2 + clearance
        for p, q in ((-dx, start[0]-left), (dx, right-start[0]), (-dy, start[1]-top), (dy, bottom-start[1])):
            if abs(p) < 1e-9:
                if q < 0:
                    break
            elif p < 0:
                lo = max(lo, q/p)
            else:
                hi = min(hi, q/p)
            if lo > hi:
                break
        else:
            return False
    return True


def outdoor_connector(start, targets, obstacles, clearance=.22):
    """Shortest visible walkway to a road node, retaining corners around buildings.

    Used at scene freeze only. No direct fallback if the entrance is enclosed.
    """
    if not targets:
        return None
    points = [tuple(start)]
    for box in obstacles:
        dx, dy = box["width"]/2+clearance+.02, box["depth"]/2+clearance+.02
        points.extend((box["x"]+sx*dx, box["y"]+sy*dy) for sx, sy in ((-1,-1),(-1,1),(1,-1),(1,1)))
    first_target = len(points)
    points.extend((p["x"], p["y"]) for p in targets)
    costs, previous, queue = {0: 0.}, {}, [(0., 0)]
    while queue:
        cost, index = heapq.heappop(queue)
        if cost > costs[index]:
            continue
        if index >= first_target:
            chain, cursor = [], index
            while cursor:
                chain.append(points[cursor]); cursor = previous[cursor]
            return list(reversed(chain)), targets[index-first_target]
        for other, point in enumerate(points):
            if other == index or not clear_segment(points[index], point, obstacles, clearance):
                continue
            candidate = cost + math.dist(points[index], point)
            if candidate < costs.get(other, math.inf):
                costs[other], previous[other] = candidate, index
                heapq.heappush(queue, (candidate, other))
    return None
