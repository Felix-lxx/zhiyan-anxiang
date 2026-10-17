"""Deterministic vehicle journeys, reconstructed from persisted dispatch events.

Targets are road nodes; connectors may only follow the current road segment.
Widths and speeds below are scenario parameters, not fire-code certification.
"""
from copy import deepcopy
import heapq
import math


def fleet(world: dict | None) -> list[dict]:
    nodes = (world or {}).get("road_network", {}).get("nodes", [])
    if not nodes:
        return []
    exits = sorted((n for n in nodes if n.get("is_exit")), key=lambda n: (n["y"], n["id"])) or nodes[:1]
    vehicles = []
    for index, (key, name, kind, width, speed) in enumerate([
        ("firetruck-1", "消防车 F-01", "firetruck", 3.5, 2.4),
        ("ambulance-1", "救护车 A-01", "ambulance", 2.8, 2.8),
    ]):
        origin = exits[min(index, len(exits) - 1)]
        vehicles.append({"id": key, "name": name, "kind": kind, "minimum_width": width, "speed": speed,
                         "x": origin["x"], "y": origin["y"], "state": "idle", "reason": f"在{origin['name']}待命，选择道路节点安排到场。",
                         "target_node_id": None, "target_name": "", "mission_id": None, "current_edge_id": None,
                         "route_points": [], "route_edge_ids": [], "progress": 0, "remaining_seconds": None, "missions": []})
    return vehicles


def plan_vehicle(network: dict, vehicle: dict, target_id: str) -> dict:
    nodes = {n["id"]: n for n in network.get("nodes", [])}
    edges = {e["id"]: e for e in network.get("edges", [])}
    start = {"x": vehicle["x"], "y": vehicle["y"]}
    result = {"route_points": [start], "route_edge_ids": [], "route_distance": 0, "planned_duration_seconds": None,
              "can_apply": False, "target_node_id": target_id, "target_name": nodes.get(target_id, {}).get("name", "未知节点"), "risk_score": 0}
    if target_id not in nodes:
        return {**result, "notice": "目标节点不属于本场冻结路网。"}
    def distance(a, b):
        return math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    def allowed(edge):
        return edge["status"] != "blocked" and edge["width_meters"] >= vehicle["minimum_width"]
    graph = {key: [] for key in nodes}
    for edge in edges.values():
        a, b = edge["start_node_id"], edge["end_node_id"]
        if a not in nodes or b not in nodes or not allowed(edge):
            continue
        length = distance(nodes[a], nodes[b])
        cost = length * (1 + max(0, edge.get("risk_score", 0)) / 100 + max(0, edge.get("density_percent", 0)) / 100)
        graph[a].append((b, cost, edge["id"]))
        graph[b].append((a, cost, edge["id"]))
    # Exact node or the current physical segment only: no nearest-node teleport.
    seeds = [(key, 0., None) for key, node in nodes.items() if distance(start, node) < .03]
    if not seeds:
        current = edges.get(vehicle.get("current_edge_id"))
        if not current or not allowed(current):
            return {**result, "notice": "车辆所在路段受阻，保持原位；恢复该路段后可重新规划。"}
        seeds = [(key, distance(start, nodes[key]), current["id"]) for key in [current["start_node_id"], current["end_node_id"]] if key in nodes]
    costs, previous, frontier = {}, {}, []
    for key, cost, edge_id in seeds:
        costs[key] = cost; previous[key] = (None, edge_id)
        heapq.heappush(frontier, (cost, key))
    while frontier:
        cost, key = heapq.heappop(frontier)
        if cost > costs[key]:
            continue
        if key == target_id:
            break
        for neighbor, weight, edge_id in graph[key]:
            if cost + weight < costs.get(neighbor, math.inf):
                costs[neighbor] = cost + weight; previous[neighbor] = (key, edge_id)
                heapq.heappush(frontier, (cost + weight, neighbor))
    if target_id not in previous:
        return {**result, "notice": f"没有满足 {vehicle['minimum_width']} 米场景通行宽度的可用路线，请恢复通道或改选目标。"}
    chain, key = [], target_id
    while key is not None:
        parent, edge_id = previous[key]
        chain.append({"x": nodes[key]["x"], "y": nodes[key]["y"], "node_id": key, "edge_id": edge_id})
        key = parent
    points = [start]
    for point in reversed(chain):
        if distance(points[-1], point) > .001:
            points.append(point)
    route_edges = list(dict.fromkeys(point["edge_id"] for point in points[1:] if point.get("edge_id")))
    length = sum(distance(a, b) for a, b in zip(points, points[1:]))
    risk = max((edges[key].get("risk_score", 0) for key in route_edges), default=0)
    traffic = max((edges[key].get("density_percent", 0) for key in route_edges), default=0)
    seconds = math.ceil(length / vehicle["speed"] * (1 + max(0, traffic) / 100))
    return {**result, "route_points": points, "route_edge_ids": route_edges, "route_distance": round(length, 2),
            "planned_duration_seconds": seconds, "can_apply": True, "risk_score": risk,
            "notice": "按场景道路宽度、封锁及拥堵规划；到达目标节点后形成到场证据。"}


def _advance(vehicle: dict, at: int):
    if vehicle["state"] != "moving":
        return
    duration = vehicle["planned_duration_seconds"]
    progress = min(1., max(0., (at - vehicle["starts_at_seconds"]) / max(1, duration))) if duration else 1.
    points = vehicle["route_points"]
    lengths = [math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * progress
    for index, length in enumerate(lengths):
        a, b = points[index], points[index + 1]
        if remaining <= length or index == len(lengths) - 1:
            ratio = min(1., remaining / max(.0001, length))
            vehicle.update(x=round(a["x"] + (b["x"] - a["x"]) * ratio, 4), y=round(a["y"] + (b["y"] - a["y"]) * ratio, 4), current_edge_id=b.get("edge_id"))
            break
        remaining -= length
    vehicle.update(progress=round(progress, 4), remaining_seconds=max(0, math.ceil(duration - (at - vehicle["starts_at_seconds"]))))
    if progress >= 1:
        vehicle.update(state="arrived", reason=f"已到达{vehicle['target_name']}，可查看到场证据或安排下一目标。", current_edge_id=None)
    mission = vehicle["missions"][-1]
    mission.update(status="completed" if progress >= 1 else "executing", progress=vehicle["progress"], remaining_seconds=vehicle["remaining_seconds"])


def vehicle_runtime(world: dict | None, events: list, elapsed: int) -> list[dict]:
    vehicles = {v["id"]: v for v in fleet(world)}
    for event in sorted((e for e in events if e.elapsed_seconds <= elapsed and e.event_type.startswith("vehicle.")), key=lambda e: (e.elapsed_seconds, e.sequence)):
        data = event.payload; vehicle = vehicles.get(data.get("vehicle_id"))
        if vehicle is None:
            continue
        _advance(vehicle, event.elapsed_seconds)
        if event.event_type == "vehicle.traffic_released" and data.get("mission_id") == vehicle["mission_id"]:
            vehicle.update(state="moving", starts_at_seconds=event.elapsed_seconds, reason="路段人员已清空，车辆沿受控通道出发。")
            vehicle["missions"][-1].update(status="executing")
            continue
        if event.event_type == "vehicle.dispatched":
            vehicle["missions"].append({"id": event.id, "label": data["target_name"], "status": "executing", "progress": 0, "remaining_seconds": data["planned_duration_seconds"]})
            vehicle["mission_id"] = event.id
        elif event.event_type == "vehicle.cancelled":
            if vehicle["missions"] and data.get("mission_id") == vehicle["mission_id"]:
                vehicle["missions"][-1].update(status="cancelled", remaining_seconds=None)
                vehicle.update(state="idle", reason="行程已取消，保留当前位置。", remaining_seconds=None, route_points=[], route_edge_ids=[])
            continue
        elif event.event_type != "vehicle.replanned" or data.get("mission_id") != vehicle["mission_id"]:
            continue
        vehicle.update({key: deepcopy(data[key]) for key in ["route_points", "route_edge_ids", "route_distance", "planned_duration_seconds", "target_node_id", "target_name"]})
        vehicle.update(starts_at_seconds=event.elapsed_seconds, state="moving" if data["can_apply"] else "blocked", progress=0,
                       reason="沿规划道路前往" + data["target_name"] if data["can_apply"] else data["notice"], remaining_seconds=data["planned_duration_seconds"])
        vehicle["missions"][-1].update(status="executing" if data["can_apply"] else "blocked", progress=0, remaining_seconds=data["planned_duration_seconds"])
        if data.get("hold_for_pedestrians") and data["can_apply"]:
            vehicle.update(state="yielding", remaining_seconds=None, reason="正在等待通道内人员走出；入口暂缓放行，清空后自动出发。")
            vehicle["missions"][-1].update(status="queued", remaining_seconds=None)
        _advance(vehicle, event.elapsed_seconds)
    for vehicle in vehicles.values():
        _advance(vehicle, elapsed)
    return list(vehicles.values())
