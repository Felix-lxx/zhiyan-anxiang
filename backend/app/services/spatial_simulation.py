"""Deterministic 3-D graph walkers with lane reservations and assembly evidence.

Version 3 never interpolates a resident between unrelated road nodes. Replanning
occurs at graph vertices; a newly blocked occupied segment is exited backwards.
Half-second stepping is identical for preview, live, replay and editable forks.
"""
from copy import deepcopy
from collections import defaultdict
import heapq
import math


def xyz(p):
    return p["x"], p["y"], p.get("height", 0)


def environment(world, events, elapsed):
    failed = world["parameters"].get("hydrant_status") in {"faulty", "failed"}
    resource, power, intensity, growth, previous = False, False, 18., 0., 0.
    for event in [*sorted((e for e in events if e["elapsed_seconds"] <= elapsed), key=lambda e: (e["elapsed_seconds"], e["sequence"])), {"elapsed_seconds": elapsed, "event_type": "", "payload": {}}]:
        rate = (1.15 if failed else .82)*(.55 if resource else 1)*(.35 if power else 1)
        delta = max(0, event["elapsed_seconds"]-previous)
        intensity = min(100., intensity+delta*rate)
        growth += delta*.34*rate/.82
        previous = event["elapsed_seconds"]
        if event["event_type"] == "inject.hydrant_failure": failed = True
        if event["event_type"] == "participant.resource_ready": resource = True
        if event["event_type"] == "task.completed" and event["payload"].get("kind") == "power_off": power = True
    return {"intensity": round(intensity, 1), "smoke_radius": round(min(48, 7+growth), 2), "temperature": round(34+intensity*3.8, 1)}, {"east_hydrant": "failed" if failed else "available", "resource_ready": resource, "power_off": power}


def simulate(world, events, elapsed, strategy=None, branch_at=None):
    graph = deepcopy(world["spatial_network"])
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    adjacent = defaultdict(list)
    for edge in edges.values():
        a, b = edge["start_node_id"], edge["end_node_id"]
        edge["length"] = max(.05, math.dist(xyz(nodes[a]), xyz(nodes[b])))
        adjacent[a].append((b, edge["id"]))
        adjacent[b].append((a, edge["id"]))
    history = sorted((e for e in events if e["elapsed_seconds"] <= elapsed), key=lambda e: (e["elapsed_seconds"], e["sequence"]))
    if strategy:
        at = elapsed if branch_at is None else branch_at
        history += [{"elapsed_seconds": at, "sequence": 10**9+i, "event_type": "resident.command", "payload": {"resident_ids": [p["id"]], "exit": "south" if strategy == "south_standard" else "north" if strategy == "north_priority" or i % 2 == 0 else "south", "action": "priority_assist" if strategy == "north_priority" and p["vulnerable"] else "evacuate"}} for i, p in enumerate(world["residents"])]
        history.sort(key=lambda e: (e["elapsed_seconds"], e["sequence"]))
    people = [{**deepcopy(p), "node_id": p["start_node_id"], "edge_id": None, "edge_progress": 0., "exit": "north" if i % 2 == 0 else "south", "status": "waiting", "release_at": 10**9, "assisted": False, "smoke_exposure": 0., "congestion": 0., "travelled": 0., "queue_seconds": 0., "counted": False, "forced_exit": False} for i, p in enumerate(world["residents"])]
    by_id = {p["id"]: p for p in people}
    helpers = {}
    now, index, revision = 0., 0, 0
    route_cache = {}
    origin = world["fire_origin"]
    fire, env = environment(world, history, 0)

    def route(start, goal):
        if start == goal: return []
        key = (revision, int(now//10), start, goal)
        if key in route_cache: return route_cache[key]
        frontier, costs, previous = [(0., start)], {start: 0.}, {}
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal: break
            for other, eid in adjacent[current]:
                edge = edges[eid]
                if edge["status"] == "blocked": continue
                mid = ((nodes[current]["x"]+nodes[other]["x"])/2, (nodes[current]["y"]+nodes[other]["y"])/2)
                risk = max(0, fire["smoke_radius"]-math.dist(mid, (origin["x"], origin["y"]))) * .1
                cost = costs[current]+edge["length"]*(1+risk)+1/edge["width_meters"]+(8 if edge["status"] == "restricted" else 0)
                if cost < costs.get(other, math.inf):
                    costs[other], previous[other] = cost, (current, eid)
                    heapq.heappush(frontier, (cost+math.dist(xyz(nodes[other]), xyz(nodes[goal])), other))
        result = None
        if goal in previous:
            result, cursor = [], goal
            while cursor != start:
                a, eid = previous[cursor]
                result.append((eid, cursor)); cursor = a
            result.reverse()
        route_cache[key] = result
        return result

    def helper_for(person, responsible):
        if person["id"] in helpers and helpers[person["id"]]["state"] != "completed": return
        outdoor = [n for n in nodes.values() if n["kind"] == "outdoor"]
        start = min(outdoor, key=lambda n: math.dist(xyz(n), xyz(world["robot_origin"]))) if outdoor else nodes["home:door"]
        helpers[person["id"]] = dict(id="helper-"+person["id"], resident_id=person["id"], node_id=start["id"], x=start["x"], y=start["y"], height=0., edge_id=None, edge_progress=0., state="approaching", responsible=responsible, travelled=0., queue_seconds=0., congestion=0.)
        person["search_responsible"] = responsible

    def destination(person): return graph.get("berths", {}).get(person["exit"], {}).get(person["id"], graph["destinations"].get(person["exit"]))

    def suffix(actor, goal):
        # An occupied blocked edge retreats continuously to the node it entered.
        anchor = actor.get("edge_from") if actor.get("edge_id") and edges[actor["edge_id"]]["status"] == "blocked" else actor.get("edge_to") if actor.get("edge_id") else actor["node_id"]
        return route(anchor, goal) if goal else None

    while True:
        while index < len(history) and history[index]["elapsed_seconds"] <= now:
            event = history[index]; payload, kind = event["payload"], event["event_type"]
            if kind in {"inject.channel_blocked", "road.reopened"}:
                edge = edges.get(payload.get("blocked_edge_id"))
                if edge:
                    edge["status"] = "blocked" if kind.startswith("inject") else "open"
                    revision += 1; route_cache.clear()
            elif kind == "resident.command":
                for pid in payload.get("resident_ids", []):
                    p = by_id.get(pid)
                    if not p or p["status"] == "evacuated": continue
                    p.update(exit=payload["exit"], forced_exit=True, release_at=min(p["release_at"], now))
                    if payload.get("action") == "priority_assist": helper_for(p, "护送员 · "+p["label"])
            elif kind == "robot.broadcast_completed":
                for p in people: p["release_at"] = min(p["release_at"], now)
            elif kind == "inject.resident_missing":
                p = by_id.get(payload.get("resident_id", "resident-3"))
                if p and p["status"] != "evacuated": p["status"] = "missing"
            elif kind == "resident.search_assigned":
                p = by_id.get(payload["resident_id"])
                if p and p["status"] != "evacuated":
                    p["status"] = "missing"
                    helper_for(p, payload["responsible"])
            elif kind == "participant.resident_counted":
                for pid in payload.get("resident_ids", []):
                    p = by_id.get(pid)
                    if p and p["status"] == "evacuated": p.update(counted=True, counted_at_seconds=now)
            index += 1
        if now >= elapsed: break
        dt = min(.5, elapsed-now, history[index]["elapsed_seconds"]-now if index < len(history) else .5)
        fire, env = environment(world, history, now)
        actors = [*people, *(h for h in helpers.values() if h["state"] in {"approaching", "blocked"})]
        occupied = defaultdict(list)
        for a in actors:
            if a.get("edge_id"): occupied[a["edge_id"]].append(a)
        # Front walkers move first; entrants retain stable FIFO priority.
        actors.sort(key=lambda a: (a.get("edge_id") or "~", -a.get("edge_progress", 0), a.get("queued_at", now), a["id"]))
        for actor in actors:
            is_helper = "resident_id" in actor
            person = by_id[actor["resident_id"]] if is_helper else actor
            actor["congestion"] = 0.
            if not is_helper:
                if person["status"] == "evacuated": continue
                density = max(0., 1-math.dist(xyz(person), (origin["x"], origin["y"], 0))/fire["smoke_radius"])
                person["smoke_exposure"] += density*dt*(1.2 if person["vulnerable"] else .85)
                helper = helpers.get(person["id"])
                if person["status"] == "missing" or (helper and helper["state"] in {"approaching", "blocked"}) or now < person["release_at"]+person.get("preparation_seconds", 3): continue
                goal = destination(person)
            else:
                goal = person.get("edge_from") if person.get("edge_id") else person["node_id"]
                if math.dist(xyz(actor), xyz(person)) <= .85:
                    actor.update(state="escorting", met_at_seconds=now)
                    person.update(assisted=True, status="waiting", found_at_seconds=now, release_at=min(person["release_at"], now))
                    continue
            if not goal: continue
            if not actor.get("edge_id"):
                path = route(actor["node_id"], goal)
                if path is None:
                    if is_helper: actor["state"] = "blocked"
                    continue
                if not path:
                    if is_helper and person.get("edge_id"):
                        path = [(person["edge_id"], person["edge_to"])]
                    elif not is_helper:
                        person.update(status="evacuated", evacuated_at_seconds=now, assembly_arrived_at_seconds=now)
                        if person["id"] in helpers: helpers[person["id"]]["state"] = "completed"
                        continue
                    else: continue
                eid, to = path[0]; edge = edges[eid]
                lanes = max(1, int(edge["width_meters"]/.8))
                if edge["status"] == "restricted": lanes = 1
                occupants = occupied[eid]
                lane = next((i for i in sorted(range(lanes), key=lambda lane: abs(lane-(lanes-1)/2)) if not any(a.get("lane") == i and (a["edge_from"] != actor["node_id"] or a["edge_progress"] < .8) for a in occupants)), None)
                if lane is None:
                    actor["queue_seconds"] += dt; actor["congestion"] = 100.; actor.setdefault("queued_at", now)
                    continue
                actor.update(edge_id=eid, edge_from=actor["node_id"], edge_to=to, edge_progress=0., lane=lane, edge_started_at=now)
                actor.pop("queued_at", None)
                occupied[eid].append(actor)
            edge = edges[actor["edge_id"]]
            retreat = edge["status"] == "blocked"
            speed = 1.6 if is_helper else (.8 if person["vulnerable"] else 1.3)*(1.2 if person["assisted"] else 1)
            if edge["kind"] == "stairs": speed *= .65
            lanes = max(1, int(edge["width_meters"]/.8)) if edge["status"] != "restricted" else 1
            lateral_amplitude = abs(actor["lane"]-(lanes-1)/2)*.55
            # Bound actual 3-D displacement including curved lane transitions.
            speed /= math.sqrt(1+(math.pi*lateral_amplitude/edge["length"])**2)
            travel = speed*dt
            progress = max(0., actor["edge_progress"]-travel) if retreat else min(edge["length"], actor["edge_progress"]+travel)
            for other in occupied[actor["edge_id"]]:
                if other is actor or other.get("lane") != actor.get("lane"): continue
                if other["edge_from"] == actor["edge_from"]:
                    if not retreat and other["edge_progress"] > actor["edge_progress"]: progress = min(progress, max(actor["edge_progress"], other["edge_progress"]-.8))
                    if retreat and other["edge_progress"] < actor["edge_progress"]: progress = max(progress, min(actor["edge_progress"], other["edge_progress"]+.8))
            if is_helper and person.get("edge_id") == actor["edge_id"] and person["edge_from"] == actor["edge_from"]:
                progress = min(progress, person["edge_progress"])
            moved = abs(progress-actor["edge_progress"])
            if moved < travel*.5: actor["queue_seconds"] += dt; actor["congestion"] = 100.
            actor["travelled"] += moved; actor["edge_progress"] = progress
            a, b = nodes[actor["edge_from"]], nodes[actor["edge_to"]]
            ratio = progress/edge["length"]
            for key in ("x", "y", "height"): actor[key] = a[key]+(b[key]-a[key])*ratio
            # Parallel lanes have separate visible centre-lines; the offset
            # fades to zero at vertices, preserving continuity on every turn.
            lanes = max(1, int(edge["width_meters"]/.8)) if edge["status"] != "restricted" else 1
            offset = (actor["lane"]-(lanes-1)/2)*.55*math.sin(math.pi*ratio)
            horizontal = math.hypot(b["x"]-a["x"], b["y"]-a["y"])
            if horizontal > .01:
                actor["x"] += -(b["y"]-a["y"])/horizontal*offset
                actor["y"] += (b["x"]-a["x"])/horizontal*offset
            if not is_helper:
                actor["status"] = "moving"
                actor["indoor_stage"] = edge["kind"] if edge["kind"] in {"room", "corridor", "stairs", "door"} else "outdoor"
                actor["current_floor"] = max(0, actor["height"]/1.92)
            else: actor["state"] = "approaching"
            if (retreat and progress <= .00001) or (not retreat and progress >= edge["length"]-.00001):
                actor["node_id"] = actor["edge_from"] if retreat else actor["edge_to"]
                occupied[actor["edge_id"]].remove(actor); actor["edge_id"] = None
                if not is_helper and actor["node_id"] == "home:door": actor.setdefault("building_exited_at_seconds", now+dt)
                if not is_helper and nodes[actor["node_id"]].get("is_exit"): actor.setdefault("exit_reached_at_seconds", now+dt)
            if not is_helper and person["id"] in helpers and helpers[person["id"]]["state"] == "escorting":
                for key in ("x", "y", "height"): helpers[person["id"]][key] = person[key]
        now += dt
    fire, env = environment(world, history, elapsed)
    for person in people:
        path = suffix(person, destination(person))
        points = [{k: person[k] for k in ("x", "y", "height")}]
        remaining = 0.
        if person.get("edge_id"):
            end = person["edge_from"] if edges[person["edge_id"]]["status"] == "blocked" else person["edge_to"]
            points.append(nodes[end]); remaining += math.dist(xyz(person), xyz(nodes[end]))
        if path:
            for eid, to in path: points.append(nodes[to]); remaining += edges[eid]["length"]
        person.update(route_reachable=path is not None, route_points=points, route_edge_ids=([person["edge_id"]] if person.get("edge_id") else [])+[eid for eid, _ in path or []], current_edge_id=person.get("edge_id"), route_distance=remaining, remaining_seconds=round(remaining/(.8 if person["vulnerable"] else 1.3)) if path is not None else 9999, estimated_seconds=round((remaining+person["travelled"])/1.3), progress=round(person["travelled"]/max(.01, person["travelled"]+remaining), 3), speed_factor=.6 if person["vulnerable"] else 1.)
        if person["status"] == "evacuated": person["indoor_stage"] = "outdoor"
        person["last_location"] = nodes[person.get("edge_from") if person.get("edge_id") else person["node_id"]]["name"] + (" → "+nodes[person["edge_to"]]["name"] if person.get("edge_id") else "")
        helper = helpers.get(person["id"])
        person["behavior"] = "集合点已核验" if person["counted"] else "已到集合点，等待清点" if person["status"] == "evacuated" else "失联，等待搜索会合" if person["status"] == "missing" else "等待护送员入楼会合" if helper and helper["state"] in {"approaching", "blocked"} else "通道排队，前人通过后前进" if person["congestion"] else "所选集合点不可达，请改道" if not person["route_reachable"] else "等待通知" if now < person["release_at"] else "准备离开房间" if now < person["release_at"]+person.get("preparation_seconds", 3) else "护送同行" if person["assisted"] else "沿连续通道撤离"
    roads = deepcopy(world["road_network"])
    for e in roads["edges"]:
        e["status"] = edges[e["id"]]["status"]
        e["risk_score"] = 100 if e["status"] == "blocked" else round(max(0, 1-math.dist(((e["start"]["x"]+e["end"]["x"])/2, (e["start"]["y"]+e["end"]["y"])/2), (origin["x"], origin["y"]))/fire["smoke_radius"])*65)
    south = [e for e in roads["edges"] if "南" in e["name"]]
    env.update(south_lane="blocked" if any(e["status"] == "blocked" for e in south) else "restricted" if any(e["status"] == "restricted" for e in south) else "open", visibility=max(8, round(100-fire["smoke_radius"]*1.8)), blockages=[{"x": (e["start"]["x"]+e["end"]["x"])/2, "y": (e["start"]["y"]+e["end"]["y"])/2, "target": e["name"], "road_edge_id": e["id"]} for e in roads["edges"] if e["status"] == "blocked"])
    return dict(fire=fire, environment=env, sensors={"temperature": fire["temperature"], "smoke_ppm": round(45+fire["smoke_radius"]*31), "alarm": fire["intensity"] >= 35}, residents=people, helpers=list(helpers.values()), world=world, spatial_network=graph, road_network=roads, strategy=strategy or "live_commands", parallel_strategy=strategy, summary=dict(total=len(people), evacuated=sum(p["status"] == "evacuated" for p in people), counted=sum(p["counted"] for p in people), moving=sum(p["status"] == "moving" for p in people), vulnerable=sum(p["vulnerable"] for p in people), missing=sum(p["status"] == "missing" for p in people), smoke_exposed=sum(p["smoke_exposure"] > 5 for p in people), congested=sum(p["congestion"] > 55 for p in people), north_load=sum(p["exit"] == "north" for p in people), south_load=sum(p["exit"] == "south" for p in people)))
