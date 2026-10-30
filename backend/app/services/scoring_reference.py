"""Freeze an explainable efficiency reference from a new world's walking graph.

This is a free-flow training reference, not a prediction of the live decision.
It includes response, preparation and escort approach time; fire and queue
outcomes are still measured independently from actual execution.
"""
import heapq
import math
from collections import defaultdict
from typing import Any
from app.services.navigation_geometry import building_obstacles, clear_segment


def build_scoring_reference(world: dict[str, Any]) -> dict[str, Any]:
    graph = world['spatial_network']
    nodes = {node['id']: node for node in graph['nodes']}
    obstacles = building_obstacles(world)
    adjacent = defaultdict(list)
    for edge in graph['edges']:
        if edge.get('status') == 'blocked' or edge.get('geometry_blocked'):
            continue
        a, b = edge['start_node_id'], edge['end_node_id']
        if edge.get('kind', 'outdoor') in {'outdoor', 'assembly'} and not clear_segment(
            (nodes[a]['x'], nodes[a]['y']), (nodes[b]['x'], nodes[b]['y']), obstacles, .22
        ):
            continue
        length = math.dist(tuple(nodes[a].get(k, 0) for k in ('x', 'y', 'height')),
                           tuple(nodes[b].get(k, 0) for k in ('x', 'y', 'height')))
        # Same stair speed factor as the authoritative walking engine.
        cost = length / (.65 if edge.get('kind') == 'stairs' else 1)
        adjacent[a].append((b, cost))
        adjacent[b].append((a, cost))

    def distances(start: str) -> dict[str, float]:
        values, queue = {start: 0.}, [(0., start)]
        while queue:
            cost, current = heapq.heappop(queue)
            if cost > values[current]:
                continue
            for target, length in adjacent[current]:
                next_cost = cost + length
                if next_cost < values.get(target, math.inf):
                    values[target] = next_cost
                    heapq.heappush(queue, (next_cost, target))
        return values

    exits = [distances(node_id) for node_id in graph['destinations'].values()]
    outside = [node for node in nodes.values() if node.get('kind') == 'outdoor']
    origin = world['robot_origin']
    staff_start = min(outside, key=lambda n: math.hypot(n['x']-origin['x'], n['y']-origin['y'])) if outside else None
    staff_routes = distances(staff_start['id']) if staff_start else {}
    staff_connector = math.hypot(staff_start['x']-origin['x'], staff_start['y']-origin['y']) if staff_start else 0
    longest, unreachable = 0., []
    for person in world['residents']:
        start = person['start_node_id']
        distance = min((route.get(start, math.inf) for route in exits), default=math.inf)
        approach = (staff_routes.get(start, math.inf) + staff_connector) / 1.6 if person['vulnerable'] else 0
        travel = distance / (.8*1.2 if person['vulnerable'] else 1.3)
        if not math.isfinite(travel + approach):
            unreachable.append(person['id'])
            continue
        longest = max(longest, travel + max(person.get('preparation_seconds', 3), approach))
    return {'version': 1, 'method': 'free_flow_with_escort',
            'target_seconds': math.ceil((longest + 30 + 10)/10)*10,
            'free_flow_seconds': round(longest, 1), 'response_allowance_seconds': 30,
            'queue_allowance_seconds': 10, 'unreachable_resident_ids': unreachable,
            'notice': '按冻结通道、楼梯速度、重点人员会合路程计算的自由流训练参考；不包含动态烟气与资源争用。'}
