"""Deterministic, event-time road simulation. No database writes or wall-clock timers."""
from __future__ import annotations

import heapq
import math
from collections import Counter


def clear_segment(start, end, obstacles: list[dict]) -> bool:
    """Liang–Barsky rectangle intersection; no straight connector through buildings."""
    for box in obstacles:
        lo, hi = 0.0, 1.0
        dx, dy = end[0] - start[0], end[1] - start[1]
        left, right = box["x"] - box["width"] / 2, box["x"] + box["width"] / 2
        top, bottom = box["y"] - box["depth"] / 2, box["y"] + box["depth"] / 2
        intersects = True
        for p, q in [(-dx, start[0] - left), (dx, right - start[0]), (-dy, start[1] - top), (dy, bottom - start[1])]:
            if abs(p) < 1e-9:
                if q < 0:
                    intersects = False
                    break
            elif p < 0:
                lo = max(lo, q / p)
            else:
                hi = min(hi, q / p)
        if intersects and lo <= hi:
            return False
    return True


def plan_route(network: dict, start: tuple[float, float], target: tuple[float, float], elapsed: float = 0) -> tuple[list[str], list[dict], list[str], float, list[dict]]:
    nodes = {node["id"]: node for node in network["nodes"]}
    if not nodes:
        return ["道路图未配置"], [{"x": start[0], "y": start[1]}], [], 0.0, []
    obstacles = network.get("obstacles", [])
    starts = [n for n in nodes.values() if clear_segment(start, (n["x"], n["y"]), obstacles)]
    ends = [n for n in nodes.values() if clear_segment(target, (n["x"], n["y"]), obstacles)]
    if not starts or not ends:
        return ["当前位置", "目标不可达"], [{"x": start[0], "y": start[1]}], [], 0.0, []
    first = min(starts, key=lambda node: math.dist(start, (node["x"], node["y"])))
    last = min(ends, key=lambda node: math.dist(target, (node["x"], node["y"])))
    adjacency: dict[str, list[tuple[str, float, str]]] = {key: [] for key in nodes}
    diagnostics = {}
    smoke_radius = min(48, 7 + elapsed * .34)
    origin = network.get("fire_origin", {"x": 66, "y": 43})
    for edge in network["edges"]:
        a, b = nodes.get(edge["start_node_id"]), nodes.get(edge["end_node_id"])
        if not a or not b or edge["status"] == "blocked":
            continue
        if not clear_segment((a["x"], a["y"]), (b["x"], b["y"]), obstacles):
            continue
        distance = math.dist((a["x"], a["y"]), (b["x"], b["y"]))
        fire_distance = math.dist(((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2), (origin["x"], origin["y"]))
        fire_penalty = max(0, smoke_radius - fire_distance) * 1.8
        width_penalty = 12 / max(1, edge["width_meters"])
        restricted_penalty = 12 if edge["status"] == "restricted" else 0
        cost = distance + fire_penalty + width_penalty + restricted_penalty
        diagnostics[edge["id"]] = {"edge_id": edge["id"], "name": edge["name"], "distance": round(distance, 2), "width_meters": edge["width_meters"], "fire_penalty": round(fire_penalty, 2), "width_penalty": round(width_penalty, 2), "restricted_penalty": restricted_penalty, "cost": round(cost, 2)}
        adjacency[a["id"]].append((b["id"], cost, edge["id"]))
        adjacency[b["id"]].append((a["id"], cost, edge["id"]))
    frontier = [(0.0, first["id"])]
    costs = {first["id"]: 0.0}
    previous: dict[str, tuple[str, str] | None] = {first["id"]: None}
    while frontier:
        _, current = heapq.heappop(frontier)
        if current == last["id"]:
            break
        for neighbor, edge_cost, edge_id in adjacency[current]:
            candidate = costs[current] + edge_cost
            if candidate < costs.get(neighbor, math.inf):
                costs[neighbor] = candidate
                previous[neighbor] = (current, edge_id)
                heuristic = math.dist((nodes[neighbor]["x"], nodes[neighbor]["y"]), (last["x"], last["y"]))
                heapq.heappush(frontier, (candidate + heuristic, neighbor))
    if last["id"] not in previous:
        return ["当前位置", "目标不可达"], [{"x": start[0], "y": start[1]}], [], 0.0, []
    node_ids, edge_ids = [], []
    cursor = last["id"]
    while cursor is not None:
        node_ids.append(cursor)
        link = previous[cursor]
        if link is None:
            break
        cursor, edge_id = link
        edge_ids.append(edge_id)
    node_ids.reverse()
    edge_ids.reverse()
    points = [{"x": start[0], "y": start[1]}]
    points.extend({"x": nodes[key]["x"], "y": nodes[key]["y"], "node_id": key} for key in node_ids)
    points.append({"x": target[0], "y": target[1]})
    distance = sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(points, points[1:]))
    return [nodes[key]["name"] for key in node_ids], points, edge_ids, round(distance, 3), [diagnostics[key] for key in edge_ids]


def sample_route(points: list[dict], distance: float) -> tuple[float, float, int]:
    if len(points) < 2:
        return points[0]["x"], points[0]["y"], 0
    for index, (a, b) in enumerate(zip(points, points[1:])):
        segment = math.dist((a["x"], a["y"]), (b["x"], b["y"]))
        if distance <= segment and segment > 0:
            ratio = max(0, distance) / segment
            return a["x"] + (b["x"] - a["x"]) * ratio, a["y"] + (b["y"] - a["y"]) * ratio, index
        distance -= segment
    return points[-1]["x"], points[-1]["y"], len(points) - 2


def simulate_residents(network: dict, events: list[dict], elapsed: int, strategy: str | None = None, branch_at: int | None = None, world: dict | None = None) -> dict:
    """Replay commands at their timestamps; rerouting never rewinds or teleports people."""
    if world and world.get("schema_version", 2) >= 3:
        from app.services.spatial_simulation import simulate
        return simulate(world, events, elapsed, strategy, branch_at)
    network = {**network, "nodes": [dict(node) for node in network["nodes"]], "edges": [dict(edge) for edge in network["edges"]]}
    origin = world["fire_origin"] if world else {"x": 66, "y": 43}
    network["fire_origin"] = origin
    fire_point = (origin["x"], origin["y"])
    edge_by_id = {edge["id"]: edge for edge in network["edges"]}
    exits = [node for node in network["nodes"] if node.get("is_exit")]
    north = next((node for node in exits if "北" in node["name"]), min(exits, key=lambda node: node["y"]) if exits else {"x": 12, "y": 12})
    south = next((node for node in exits if "南" in node["name"]), max(exits, key=lambda node: node["y"]) if exits else {"x": 84, "y": 88})
    targets = {"north": (north["x"], north["y"]), "south": (south["x"], south["y"])}
    people = []
    for index in range(len(world["residents"]) if world else 18):
        origin = (58.0, 48.0) if index < 10 else (34.0, 68.0)
        vulnerable = index in {2, 7, 14}
        people.append({"id": f"resident-{index + 1}", "label": f"居民 {index + 1:02d}", "vulnerable": vulnerable, "x": origin[0] + ((index % 3) - 1) * 1.15, "y": origin[1] + ((index % 4) - 1.5) * .9, "exit": "north" if index % 2 == 0 else "south", "assisted": False, "forced_exit": False, "release_at": index * 1.35 + (8 if vulnerable else 0), "status": "waiting", "smoke_exposure": 0.0, "congestion": 0.0, "travelled": 0.0})
        if world:
            people[-1].update(world["residents"][index])
            people[-1]["release_at"] = 1_000_000_000

    def reroute(person: dict, at: float) -> None:
        _, points, edges, distance, _ = plan_route(network, (person["x"], person["y"]), targets[person["exit"]], at)
        if len(points) < 2 and not person["forced_exit"]:
            person["exit"] = "south" if person["exit"] == "north" else "north"
            _, points, edges, distance, _ = plan_route(network, (person["x"], person["y"]), targets[person["exit"]], at)
        person.update(route_points=points, route_edge_ids=edges, route_distance=distance, path_travel=0.0, route_reachable=len(points) > 1, segment=0)

    for person in people:
        reroute(person, 0)
    events = sorted((event for event in events if event["elapsed_seconds"] <= elapsed), key=lambda event: (event["elapsed_seconds"], event["sequence"]))
    event_index, now, intensity = 0, 0.0, 18.0
    hydrant_failed = bool(world and world.get("parameters", {}).get("hydrant_status") == "failed")
    resource_ready = False
    power_off = False
    helpers = {}
    branch_applied = strategy is None
    branch_at = elapsed if branch_at is None else branch_at
    blockages = []

    def apply_strategy(at: float) -> None:
        for index, person in enumerate(people):
            if person["status"] == "evacuated":
                continue
            person["forced_exit"] = True
            person["exit"] = "south" if strategy == "south_standard" else ("north" if strategy == "north_priority" or index % 2 == 0 else "south")
            person["assisted"] = strategy == "north_priority" and person["vulnerable"]
            person["release_at"] = min(person["release_at"], at)
            reroute(person, at)

    while True:
        while event_index < len(events) and events[event_index]["elapsed_seconds"] <= now:
            event = events[event_index]
            payload, kind = event["payload"], event["event_type"]
            if kind in {"inject.channel_blocked", "road.reopened"}:
                edge = edge_by_id.get(payload.get("blocked_edge_id"))
                if edge:
                    edge["status"], edge["blocked_by_event"] = ("blocked", True) if kind == "inject.channel_blocked" else ("open", False)
                    blockages = [b for b in blockages if b["road_edge_id"] != edge["id"]]
                    if kind == "inject.channel_blocked":
                        blockages.append({"x": payload.get("x", (edge["start"]["x"] + edge["end"]["x"]) / 2), "y": payload.get("y", (edge["start"]["y"] + edge["end"]["y"]) / 2), "target": edge["name"], "road_edge_id": edge["id"]})
                    for person in people:
                        if person["status"] != "evacuated":
                            reroute(person, now)
                        helper = helpers.get(person["id"])
                        if helper and helper["state"] in {"approaching", "blocked"}:
                            _, route, _, distance, _ = plan_route(network, (helper["x"], helper["y"]), (person["x"], person["y"]), now)
                            helper.update(route_points=route, distance=distance, travel=0.0, state="approaching" if len(route) > 1 else "blocked")
            elif kind == "resident.command":
                for person in people:
                    if person["id"] in payload.get("resident_ids", []) and person["status"] != "evacuated":
                        person.update(exit=payload["exit"], assisted=person["assisted"] or payload.get("action") == "priority_assist", forced_exit=True)
                        if world and person["assisted"] and person["id"] not in helpers:
                            start = world["robot_origin"]
                            _, route, _, distance, _ = plan_route(network, (start["x"], start["y"]), (person["x"], person["y"]), now)
                            helpers[person["id"]] = {"id": "helper-" + person["id"], "resident_id": person["id"], "x": start["x"], "y": start["y"], "route_points": route, "distance": distance, "travel": 0.0, "state": "approaching" if len(route) > 1 else "blocked"}
                            person["status"] = "waiting_for_helper"
                        person["release_at"] = min(person["release_at"], now)
                        reroute(person, now)
            elif kind == "robot.broadcast_completed":
                for person in people:
                    person["release_at"] = min(person["release_at"], now)
            elif kind == "inject.hydrant_failure":
                hydrant_failed = True
            elif kind == "participant.resource_ready":
                resource_ready = True
            elif kind == "task.completed" and payload.get("kind") == "power_off":
                power_off = True
            elif kind == "inject.resident_missing":
                person = next((item for item in people if item["id"] == payload.get("resident_id", "resident-3")), people[min(2, len(people) - 1)])
                if person["status"] != "evacuated":
                    person["status"] = "missing"
            elif kind == "participant.resident_counted":
                for person in people:
                    if person["status"] == "missing" and (not world or person["id"] in payload.get("resident_ids", [])):
                        person.update(status="waiting", assisted=person["assisted"] if world else person["vulnerable"], release_at=now)
                        reroute(person, now)
            event_index += 1
        if not branch_applied and now >= branch_at:
            apply_strategy(now)
            branch_applied = True
        if now >= elapsed:
            break
        future = [float(elapsed)]
        if event_index < len(events):
            future.append(float(events[event_index]["elapsed_seconds"]))
        if not branch_applied:
            future.append(float(branch_at))
        dt = min(1.0 if now < 600 else 5.0, min(future) - now)
        if all(person["status"] == "evacuated" for person in people):
            dt = min(future) - now
        intensity = min(100, intensity + dt * (1.15 if hydrant_failed else .82) * (.55 if resource_ready else 1) * (.35 if power_off else 1))
        smoke_radius = min(48, 7 + now * .34)
        occupancy: Counter[str] = Counter()
        for person in people:
            edges = person["route_edge_ids"]
            key = edges[min(max(0, person["segment"] - 1), len(edges) - 1)] if edges else f"exit:{person['exit']}"
            person["current_edge_id"] = key
            if person["status"] != "evacuated" and now >= person["release_at"] and person.get("indoor_stage", "outdoor") == "outdoor":
                occupancy[key] += 1
        stairs = Counter((p.get("building_id"), math.ceil(p.get("current_floor", 0))) for p in people if p.get("indoor_stage") == "stairs")
        exit_slots = Counter()
        for person in people:
            if person["status"] == "evacuated":
                person["congestion"] = 0.0
                continue
            edge = edge_by_id.get(person["current_edge_id"], {})
            capacity = max(2.0, edge.get("width_meters", 3.0) * 1.6)
            congestion = min(100.0, max(0.0, occupancy[person["current_edge_id"]] - capacity) / capacity * 85)
            person["congestion"] = congestion
            smoke_density = max(0.0, 1 - math.dist((person["x"], person["y"]), fire_point) / max(1, smoke_radius))
            person["smoke_exposure"] += smoke_density * dt * (1.2 if person["vulnerable"] else .85)
            helper = helpers.get(person["id"])
            indoor = person.get("indoor_stage", "outdoor") != "outdoor"
            if helper and helper["state"] in {"approaching", "blocked"}:
                if helper["state"] == "approaching":
                    helper["travel"] = min(helper["distance"], helper["travel"] + 2.8 * dt)
                    helper["x"], helper["y"], _ = sample_route(helper["route_points"], helper["travel"])
                    if helper["travel"] >= helper["distance"]:
                        helper["state"] = "escorting"
                if not indoor:
                    continue
            if indoor:
                if person["status"] == "missing" or now < person["release_at"]:
                    continue
                if now < person["release_at"] + person["preparation_seconds"]:
                    person["indoor_stage"] = "preparing"
                    continue
                if person["indoor_remaining"] > 0:
                    load = stairs[(person.get("building_id"), math.ceil(person["current_floor"]))]
                    person["indoor_stage"] = "stairs"
                    person["congestion"] = min(100, max(0, load - 3) * 12)
                    speed = (.6 if person["vulnerable"] else 1.1) / max(1, load / 3)
                    person["indoor_remaining"] = max(0, person["indoor_remaining"] - speed * dt)
                    person["current_floor"] = person["indoor_remaining"] / 6
                    continue
                person["indoor_stage"] = "exit_queue"
                building = person.get("building_id")
                if exit_slots[building] >= 2 * dt:
                    continue
                exit_slots[building] += 1
                person["indoor_stage"] = "outdoor"
                person["building_exited_at_seconds"] = now + dt
                # Do not reuse the same time step for outside movement.
                continue
            if person["status"] == "missing" or now < person["release_at"] or not person["route_reachable"]:
                continue
            speed_factor = (.58 if person["vulnerable"] else 1.0) * (1.42 if person["assisted"] else 1.0)
            distance = min(max(0, person["route_distance"] - person["path_travel"]), 1.6 * speed_factor * (1 - congestion * .006) * (1 - smoke_density * .3) * dt)
            person["path_travel"] += distance
            person["travelled"] += distance
            person["x"], person["y"], person["segment"] = sample_route(person["route_points"], person["path_travel"])
            if helper:
                helper.update(x=person["x"], y=person["y"], state="escorting")
            person["status"] = "evacuated" if person["path_travel"] >= person["route_distance"] - .001 else "moving"
            if person["status"] == "evacuated":
                person["evacuated_at_seconds"] = now + dt
                if helper:
                    helper["state"] = "completed"
        now += dt

    for person in people:
        remaining = max(0, person["route_distance"] - person["path_travel"])
        helper = helpers.get(person["id"])
        person["progress"] = round(person["travelled"] / max(.001, person["travelled"] + remaining), 3) if person["route_reachable"] else 0.0
        person["speed_factor"] = round((.58 if person["vulnerable"] else 1.0) * (1.42 if person["assisted"] else 1.0), 3)
        person["remaining_seconds"] = round(remaining / max(.1, 1.6 * person["speed_factor"] * (1 - person["congestion"] * .006)) + max(0, person["release_at"] - elapsed)) if person["route_reachable"] else 9999
        person["estimated_seconds"] = round((person["travelled"] + remaining) / max(.1, 1.6 * person["speed_factor"]))
        person["behavior"] = ("已到达安全出口" if person["status"] == "evacuated" else "等待护送员会合" if helpers.get(person["id"], {}).get("state") in {"approaching", "blocked"} else "脱离队伍，等待搜索定位" if person["status"] == "missing" else "所选出口不可达，等待重新分流" if not person["route_reachable"] else "重点人员护送中" if person["assisted"] else "路段拥堵，减速跟随队伍" if person["congestion"] > 55 else "烟气区域内低速撤离" if person["smoke_exposure"] > 5 else "沿道路网疏散" if person["status"] == "moving" else "等待疏散指令")
        if person.get("indoor_stage", "outdoor") != "outdoor" and person["status"] != "missing":
            person["behavior"] = {"room": "楼内等待疏散通知", "preparing": "收到通知，正在离开房间", "stairs": "楼梯排队下行" if person["congestion"] > 0 else "沿楼梯下行", "exit_queue": "楼门排队，等待通行"}[person["indoor_stage"]]
        if person.get("indoor_stage") == "outdoor" and helper and helper["state"] == "escorting" and person["status"] == "waiting":
            person["behavior"] = "护送员已到入口，正在会合"
        for key in ("x", "y", "smoke_exposure", "congestion"):
            person[key] = round(person[key], 2)
    south_edges = [edge for edge in network["edges"] if "南" in edge["name"]]
    south_lane = "blocked" if any(edge["status"] == "blocked" for edge in south_edges) else "restricted" if any(edge["status"] == "restricted" for edge in south_edges) else "open"
    smoke_radius = min(48, 7 + elapsed * .34)
    for edge in network["edges"]:
        midpoint = ((edge["start"]["x"] + edge["end"]["x"]) / 2, (edge["start"]["y"] + edge["end"]["y"]) / 2)
        edge["risk_score"] = 100 if edge["status"] == "blocked" else min(99, round(max(0, 1 - math.dist(midpoint, fire_point) / smoke_radius) * 65 + 35 / max(1, edge["width_meters"])))
    return {
        "fire": {"intensity": round(intensity, 1), "smoke_radius": round(smoke_radius, 1), "temperature": round(34 + intensity * 3.8, 1)},
        "environment": {"south_lane": south_lane, "east_hydrant": "failed" if hydrant_failed else "available", "visibility": max(8, round(100 - smoke_radius * 1.8)), "blockages": blockages, "resource_ready": resource_ready, "power_off": power_off},
        "sensors": {"temperature": round(30 + intensity * 2.9, 1), "smoke_ppm": round(45 + smoke_radius * 31), "alarm": intensity >= 35},
        "residents": people,
        "helpers": list(helpers.values()),
        "world": world,
        "summary": {"total": len(people), "evacuated": sum(p["status"] == "evacuated" for p in people), "moving": sum(p["status"] == "moving" for p in people), "vulnerable": sum(p["vulnerable"] for p in people), "missing": sum(p["status"] == "missing" for p in people), "smoke_exposed": sum(p["smoke_exposure"] > 5 for p in people), "congested": sum(p["congestion"] > 55 for p in people), "north_load": sum(p["exit"] == "north" for p in people), "south_load": sum(p["exit"] == "south" for p in people)},
        "road_network": network, "strategy": strategy or "live_commands", "parallel_strategy": strategy,
    }
