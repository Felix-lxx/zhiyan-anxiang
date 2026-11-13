"""Deterministic 3-D graph walkers with lane reservations and assembly evidence.

Version 3 never interpolates a resident between unrelated road nodes. Replanning
occurs at graph vertices; a newly blocked occupied segment is exited backwards.
Half-second stepping is identical for preview, live, replay and editable forks.
"""
from copy import deepcopy
from collections import defaultdict
import heapq
import math
from app.services.escort_motion import can_meet, follow_walked_path
from app.services.navigation_geometry import building_obstacles, clear_segment
from app.services.response_staff import roster as staff_roster, projection as staff_projection
from app.services.indoor_fire import zone_density
from app.services.motion_trace import record_motion
from app.services.exposure import accumulate_exposure


def xyz(p):
    return p["x"], p["y"], p.get("height", 0)


def environment(world, events, elapsed):
    from app.services.fire_environment import EnvironmentTimeline
    return EnvironmentTimeline(world, events).at(elapsed)


def simulate(world, events, elapsed, strategy=None, branch_at=None, *, checkpoint=None, checkpoint_out=None):
    # Nodes/endpoints are frozen inputs. Only edge runtime fields are writable.
    # Avoid cloning thousands of immutable room/berth nodes on every live read.
    graph = {**world["spatial_network"], "edges": [dict(edge) for edge in world["spatial_network"]["edges"]]}
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    obstacles = building_obstacles(world)
    invalid_edges = set()
    adjacent = defaultdict(list)
    for edge in edges.values():
        a, b = edge["start_node_id"], edge["end_node_id"]
        if edge.get("kind", "outdoor") in {"outdoor", "assembly"} and not clear_segment(
                (nodes[a]["x"], nodes[a]["y"]), (nodes[b]["x"], nodes[b]["y"]), obstacles, .22):
            edge.update(status="blocked", geometry_blocked=True, blocked_reason="通道与楼体或人员净距范围相交，请调整地图后新建场次。")
            invalid_edges.add(edge["id"])
        edge["length"] = max(.05, math.dist(xyz(nodes[a]), xyz(nodes[b])))
        adjacent[a].append((b, edge["id"]))
        adjacent[b].append((a, edge["id"]))
    history = sorted((e for e in events if e["elapsed_seconds"] <= elapsed), key=lambda e: (e["elapsed_seconds"], e["sequence"]))
    if strategy:
        at = elapsed if branch_at is None else branch_at
        history += [{"elapsed_seconds": at, "sequence": 10**9+i, "event_type": "resident.command", "payload": {"resident_ids": [p["id"]], "exit": "south" if strategy == "south_standard" else "north" if strategy == "north_priority" or i % 2 == 0 else "south", "action": "priority_assist" if strategy == "north_priority" and p["vulnerable"] else "evacuate"}} for i, p in enumerate(world["residents"])]
        history.sort(key=lambda e: (e["elapsed_seconds"], e["sequence"]))
    from app.services.fire_environment import EnvironmentTimeline
    environment_at = EnvironmentTimeline(world, history).at
    from app.services.vehicle_traffic import TrafficTimeline
    traffic_at = TrafficTimeline(history).at
    people = []
    by_id = {p["id"]: p for p in people}
    helpers = {}
    now, index, revision, flow_revision = 0., 0, 0, 0
    route_cache = {}
    restored = False
    # Restore raw walkers, not the presentation snapshot (which contains derived routes).
    # Appended same-tick events are allowed; retroactive edits invalidate the prefix.
    from app.services.simulation_checkpoints import digest, ENGINE_REVISION
    if checkpoint and not strategy:
        saved_index = checkpoint.get("index", -1)
        saved_time = checkpoint.get("now", -1)
        valid = (
            checkpoint.get("revision_id") == ENGINE_REVISION
            and 0 <= saved_time <= elapsed and saved_time * 2 == int(saved_time * 2)
            and 0 <= saved_index <= len(history)
            and checkpoint.get("world_digest") == digest(world)
            and checkpoint.get("history_digest") == digest(history[:saved_index])
            and (saved_index == len(history) or history[saved_index]["elapsed_seconds"] >= saved_time)
        )
        if valid:
            restored = True
            people, helpers = deepcopy(checkpoint["people"]), deepcopy(checkpoint["helpers"])
            by_id = {p["id"]: p for p in people}
            now, index = saved_time, saved_index
            revision, flow_revision = checkpoint["revision"], checkpoint["flow_revision"]
            route_cache = {tuple(key): deepcopy(value) for key, value in checkpoint["routes"]}
            for eid, status in checkpoint["edge_statuses"].items(): edges[eid]["status"] = status
    if not restored:
        people = [{**deepcopy(p), "node_id": p["start_node_id"], "edge_id": None, "edge_progress": 0., "exit": "north" if i % 2 == 0 else "south", "status": "waiting", "release_at": 10**9, "assisted": False, "smoke_exposure": 0., "congestion": 0., "travelled": 0., "queue_seconds": 0., "counted": False, "forced_exit": False} for i, p in enumerate(world["residents"])]
        by_id = {p["id"]: p for p in people}
    staff = staff_roster(world)
    for actor in [*people, *helpers.values()]:
        record_motion(actor, now)
    flow_dirty = False
    origin = world["fire_origin"]
    fire, env = environment_at(now)
    def sync_doors():
        nonlocal revision
        changed = False
        for door in env.get('indoor', {}).get('doors', []):
            edge = edges.get(door['id'])
            if edge is not None:
                status = 'blocked' if door['state'] == 'closed' else 'open'
                if edge['status'] != status: edge['status'] = status; changed = True
        if changed: revision += 1; route_cache.clear()
    def exposure_density(actor):
        if world.get('indoor_environment'):
            edge = edges.get(actor.get('edge_id'))
            ratio = actor.get('edge_progress', 0)/edge['length'] if edge else 0
            if edge and actor.get('edge_from') != edge['start_node_id']: ratio = 1-ratio
            return zone_density(env, actor.get('node_id'), edge, ratio)
        if world.get('outdoor_smoke_domain') == 'exterior_v1':
            edge = edges.get(actor.get('edge_id'))
            node = nodes.get(actor.get('node_id'), {})
            if (edge and edge.get('kind') not in {'outdoor', 'assembly'}) or (not edge and node.get('kind') not in {'outdoor', 'assembly', 'door'}):
                return 0.
        return max(0., 1-math.dist(xyz(actor), (origin['x'], origin['y'], 0))/max(.01, fire['smoke_radius'])) if fire['smoke_radius'] > 0 else 0
    sync_doors()
    occupied = defaultdict(list)
    waiting_counts = defaultdict(int)
    if restored:
        actors_by_id = {a["id"]: a for a in [*people, *helpers.values()]}
        occupied.update({eid: [actors_by_id[aid] for aid in ids] for eid, ids in checkpoint.get("occupied", {}).items()})
        waiting_counts.update(checkpoint.get("waiting_counts", {}))

    def lane_count(edge):
        return 1 if edge["status"] == "restricted" else max(1, int(edge["width_meters"]/.8))

    def edge_capacity(edge):
        # Capacity is a physical occupancy bound, not a score: parallel lanes
        # multiplied by 0.8 m pedestrian headway along the segment.
        return max(1, lane_count(edge) * max(1, int(edge["length"]/.8)))

    def footprint(actor):
        return 1.5 if actor.get('assisted') else .8

    def pressure(eid):
        edge = edges[eid]
        # A walking escort pair reserves more longitudinal space than one actor.
        load = sum(footprint(actor)/.8 for actor in occupied.get(eid, ())) + waiting_counts.get(eid, 0) * .72
        return min(2., load / edge_capacity(edge))

    def invalidate_flow():
        nonlocal flow_dirty
        # One routing pressure epoch per half-second, not one A* cache purge
        # per walker. Physical lane admission below always uses current occupancy.
        flow_dirty = True

    def route(start, goal):
        # Each person's private assembly berth is a leaf, not a distinct A* goal.
        # Share the road-to-hub search; preserve their unique final walking segment.
        if start != goal and nodes[goal]["kind"] == "assembly" and len(adjacent[goal]) == 1:
            hub, eid = adjacent[goal][0]
            if edges[eid]["status"] == "blocked" or eid in invalid_edges: return None
            path = route_core(start, hub)
            return None if path is None else [*path, (eid, goal)]
        return route_core(start, goal)

    def route_core(start, goal):
        if start == goal: return []
        key = (revision, flow_revision, int(now//4), start, goal)
        if key in route_cache: return route_cache[key]
        frontier, costs, previous = [(0., start)], {start: 0.}, {}
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal: break
            for other, eid in adjacent[current]:
                # Rooms and private berths cannot be transit shortcuts.
                if other != goal and len(adjacent[other]) == 1: continue
                edge = edges[eid]
                if edge["status"] == "blocked" or eid in invalid_edges: continue
                mid = ((nodes[current]["x"]+nodes[other]["x"])/2, (nodes[current]["y"]+nodes[other]["y"])/2)
                risk = zone_density(env, edge=edge)*3 if world.get('indoor_environment') else max(0, fire["smoke_radius"]-math.dist(mid, (origin["x"], origin["y"]))) * .1
                if world.get('outdoor_smoke_domain') == 'exterior_v1' and edge.get('kind') not in {'outdoor', 'assembly'}:
                    risk = 0.
                congestion = pressure(eid)
                queue = waiting_counts.get(eid, 0)
                # A* weighs current occupancy and the queue at the segment
                # entrance. Full segments remain traversable when no safe
                # alternative exists, but alternatives become preferable.
                traffic_penalty = congestion * congestion * max(6., edge["length"]*.72) + queue*1.4
                cost = costs[current]+edge["length"]*(1+risk)+1/edge["width_meters"]+(8 if edge["status"] == "restricted" else 0)+traffic_penalty
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

    def preparation_end(person):
        if person.get('notification_confirmed_at') is not None:
            return max(person['release_at'], person['notification_confirmed_at']+person.get('preparation_seconds', 3))
        return person['release_at']+person.get('preparation_seconds', 3)

    def last_staff_node(previous):
        # Escorted walkers retain their approach node while following the
        # resident's trail. Reuse the completed assembly berth, not that stale
        # room node; visitors stop on their own graph node.
        node_id = (previous['node_id'] if previous.get('purpose')=='household_visit'
                   else by_id[previous['resident_id']]['node_id'])
        return nodes[node_id]

    def helper_for(person, responsible, assigned_staff=None):
        if person["id"] in helpers and helpers[person["id"]]["state"] != "completed": return
        busy = {h.get("staff_id") for h in helpers.values() if h["state"] != "completed"}
        from app.services.task_staff import occupations
        busy.update(t["staff_id"] for t in occupations(history[:index+1]).values())
        slot = next((s for s in staff if s.get("available", True) and s["id"] not in busy
                     and (assigned_staff is None or s['id'] == assigned_staff)), None)
        if slot is None: return
        outdoor = [n for n in nodes.values() if n["kind"] == "outdoor"]
        origin = slot.get("origin", world["robot_origin"])
        start = min(outdoor, key=lambda n: math.dist(xyz(n), xyz(origin))) if outdoor else next(n for n in nodes.values() if n["kind"] == "door" and n.get("building_id") == person.get("building_id"))
        previous = next((h for h in reversed(list(helpers.values())) if h.get("staff_id") == slot["id"] and h["state"] == "completed"), None)
        if previous:
            start = last_staff_node(previous)
        binding = next((e["payload"] for e in reversed(history[:index+1]) if e["event_type"] == "staff.bound" and e["payload"].get("staff_id") == slot["id"]), None)
        responsible = (binding or {}).get("responsible") or responsible
        helpers[person["id"]] = dict(id="helper-"+person["id"], staff_id=slot["id"], staff_name=slot["name"], participant_id=(binding or {}).get("participant_id"), resident_id=person["id"], node_id=start["id"], x=start["x"], y=start["y"], height=start.get("height", 0.), edge_id=None, edge_progress=0., state="approaching", responsible=responsible, travelled=0., queue_seconds=0., congestion=0., started_at_seconds=now)
        person["search_responsible"] = responsible

    def destination(person): return graph.get("berths", {}).get(person["exit"], {}).get(person["id"], graph["destinations"].get(person["exit"]))

    def visit_goal(actor):
        if actor.get('cancelling'):
            return (actor['edge_from'] if edges[actor['edge_id']]['status']=='blocked'
                    else actor['edge_to']) if actor.get('edge_id') else actor['node_id']
        return actor['target_node_id']

    def suffix(actor, goal):
        # An occupied blocked edge retreats continuously to the node it entered.
        anchor = actor.get("edge_from") if actor.get("edge_id") and edges[actor["edge_id"]]["status"] == "blocked" else actor.get("edge_to") if actor.get("edge_id") else actor["node_id"]
        return route(anchor, goal) if goal else None

    while True:
        if flow_dirty:
            flow_revision += 1
            route_cache.clear()
            flow_dirty = False
        while index < len(history) and history[index]["elapsed_seconds"] <= now:
            event = history[index]; payload, kind = event["payload"], event["event_type"]
            if kind in {"inject.channel_blocked", "road.reopened"}:
                edge = edges.get(payload.get("blocked_edge_id"))
                if edge:
                    edge["status"] = "blocked" if kind.startswith("inject") or edge["id"] in invalid_edges else "open"
                    revision += 1; route_cache.clear()
            elif kind == "resident.command":
                for pid in payload.get("resident_ids", []):
                    p = by_id.get(pid)
                    if not p or p["status"] == "evacuated": continue
                    p.update(exit=payload["exit"], forced_exit=True, awaiting_escort=False, release_at=min(p["release_at"], now))
                    if payload.get("action") == "priority_assist": helper_for(p, "护送员 · "+p["label"], payload.get('staff_assignments', {}).get(pid))
            elif kind == "robot.broadcast_completed":
                if world.get('community_training'):
                    # Coverage is not receipt; only a reported confirmation or
                    # an explicit resident command releases these households.
                    index += 1
                    continue
                # A robot broadcasting at one building entrance must not wake
                # every building in the community.  Old events without an
                # explicit scope remain global for replay compatibility.
                building_id = payload.get("building_id")
                resident_ids = set(payload.get("resident_ids", []))
                awaiting_escort = set(payload.get('awaiting_escort_ids', []))
                for p in people:
                    if (not building_id and not resident_ids
                            or building_id and p.get("building_id") == building_id
                            or p["id"] in resident_ids):
                        p["release_at"] = min(p["release_at"], now)
                        if p['id'] in awaiting_escort and not p.get('forced_exit'):
                            p['awaiting_escort'] = True
            elif kind == "inject.resident_missing":
                p = by_id.get(payload.get("resident_id", "resident-3"))
                if p and p["status"] != "evacuated": p["status"] = "missing"
            elif kind == 'participant.household_confirmed':
                for p in people:
                    if p.get('household_id') == payload.get('household_id'):
                        p.setdefault('notification_confirmed_at', now)
                for visitor in helpers.values():
                    if visitor.get('household_id') == payload.get('household_id') and visitor['state']!='completed':
                        if not visitor.get('edge_id'):
                            visitor.update(state='completed', completed_at_seconds=now)
                        else:
                            visitor['cancelling'] = True
            elif kind == 'participant.household_visit':
                p = by_id.get(payload.get('resident_id'))
                slot = next((s for s in staff if s['id']==payload.get('staff_id')), None)
                if p and slot and payload.get('target_node_id') in nodes:
                    previous = next((h for h in reversed(list(helpers.values()))
                                     if h.get('staff_id')==slot['id'] and h['state']=='completed'), None)
                    outdoor = [n for n in nodes.values() if n['kind']=='outdoor']
                    start = last_staff_node(previous) if previous else min(outdoor,
                        key=lambda n: math.dist(xyz(n), xyz(slot.get('origin', world['robot_origin']))))
                    vid = 'visit:'+str(event['sequence'])
                    helpers[vid] = dict(id=vid, purpose='household_visit', household_id=payload['household_id'],
                        target_node_id=payload['target_node_id'], resident_id=p['id'], building_id=p['building_id'],
                        staff_id=slot['id'], staff_name=slot['name'], participant_id=payload.get('participant_id'),
                        responsible=payload.get('responsible'), node_id=start['id'], x=start['x'], y=start['y'],
                        height=start.get('height', 0), state='approaching', edge_id=None, edge_progress=0.,
                        travelled=0., queue_seconds=0., congestion=0., started_at_seconds=now)
            elif kind == 'participant.household_visit_cancel':
                visitor = helpers.get(payload.get('visit_id'))
                if visitor and visitor['state']!='completed':
                    visitor['cancelling'] = True
                    if not visitor.get('edge_id'):
                        visitor.update(state='completed', completed_at_seconds=now)
            elif kind == "resident.search_assigned":
                p = by_id.get(payload["resident_id"])
                if p and p["status"] != "evacuated":
                    p["status"] = "missing"
                    helper_for(p, payload["responsible"], payload.get('staff_assignments', {}).get(p['id']))
            elif kind == "participant.resident_counted":
                for pid in payload.get("resident_ids", []):
                    p = by_id.get(pid)
                    if p and p["status"] == "evacuated": p.update(counted=True, counted_at_seconds=now)
            index += 1
        if now >= elapsed: break
        dt = min(.5, elapsed-now, history[index]["elapsed_seconds"]-now if index < len(history) else .5)
        fire, env = environment_at(now)
        sync_doors()
        visit_smoke_limit = (world.get('community_training') or {}).get('visit_smoke_limit', .15)
        for visitor in helpers.values():
            if visitor.get('purpose')=='household_visit' and visitor['state']=='at_door' and zone_density(env, visitor['node_id']) > visit_smoke_limit:
                visitor.update(state='blocked', risk_blocked=True)
        reserved_roads = traffic_at(now)
        # Dormant sessions can be days old. Once smoke has saturated, waiting
        # actors have constant exposure and no positional changes. Integrate that
        # interval directly, stopping BEFORE the next event or preparation end.
        # Never skip moving walkers, queues, approaching helpers, or a changing
        # environment; those retain the original half-second capacity rules.
        stationary = (
            not world.get('indoor_environment') and fire["smoke_radius"] >= 48
            and not env.get("water_suppression")
            and not any(h["state"] == "approaching" or h.get("edge_id") for h in helpers.values())
            and all(not p.get("edge_id") and (
                p["status"] in {"evacuated", "missing"}
                or now < preparation_end(p)
                or p.get('awaiting_escort')
                or (helpers.get(p["id"], {}).get("state") == "blocked")
                or not destination(p) or route(p["node_id"], destination(p)) is None
            ) for p in people)
        )
        if stationary:
            boundary = min(float(elapsed), float(history[index]["elapsed_seconds"]) if index < len(history) else float(elapsed))
            for person in people:
                ready_at = preparation_end(person)
                if person["status"] not in {"evacuated", "missing"} and ready_at > now:
                    boundary = min(boundary, ready_at)
            skipped = math.floor((boundary-now)/.5)*.5
            if skipped > .5:
                for person in people:
                    person["congestion"] = 0.
                    if person["status"] != "evacuated":
                        density = exposure_density(person)
                        accumulate_exposure(person, density, skipped, now)
                now += skipped
                continue
        actors = [*people, *(h for h in helpers.values() if h["state"] in {"approaching", "blocked"})]
        for actor in actors:
            record_motion(actor, now)
        occupied = defaultdict(list)
        waiting_counts = defaultdict(int)
        for a in actors:
            if a.get("edge_id"): occupied[a["edge_id"]].append(a)
            if a.get("waiting_for_edge"): waiting_counts[a["waiting_for_edge"]] += 1
        # Front walkers move first; entrants retain stable FIFO priority.
        actors.sort(key=lambda a: (a.get("edge_id") or "~", -a.get("edge_progress", 0), a.get("queued_at", now), a["id"]))
        for actor in actors:
            is_helper = "resident_id" in actor
            person = by_id[actor["resident_id"]] if is_helper else actor
            actor["congestion"] = 0.
            if not is_helper:
                if person["status"] == "evacuated": continue
                density = exposure_density(person)
                accumulate_exposure(person, density, dt, now)
                helper = helpers.get(person["id"])
                # Finish (or retreat out of) the occupied segment before waiting
                # for assistance; freezing inside it can block the approaching helper.
                if person.get('awaiting_escort') and not person.get('edge_id'):
                    person['status'] = 'waiting'
                    continue
                if person["status"] == "missing" or (helper and helper["state"] in {"approaching", "blocked"} and not person.get('edge_id')) or now < preparation_end(person): continue
                goal = destination(person)
            else:
                is_visit = actor.get('purpose') == 'household_visit'
                goal = visit_goal(actor) if is_visit else person.get("edge_from") if person.get("edge_id") else person["node_id"]
                if is_visit and not actor.get('edge_id') and actor['node_id']==goal:
                    if not actor.get('cancelling') and zone_density(env, goal) > visit_smoke_limit:
                        actor.update(state='blocked', risk_blocked=True)
                        continue
                    actor.pop('risk_blocked', None)
                    actor.update(state='completed' if actor.get('cancelling') else 'at_door', arrived_at_seconds=now)
                    continue
                if not is_visit and can_meet(actor, person, edges):
                    if actor.get('edge_id') and actor in occupied[actor['edge_id']]:
                        occupied[actor['edge_id']].remove(actor)
                    actor.update(state="escorting", met_at_seconds=now, edge_id=None)
                    previous_wait = actor.pop('waiting_for_edge', None)
                    if previous_wait:
                        waiting_counts[previous_wait] = max(0, waiting_counts[previous_wait]-1)
                    invalidate_flow()
                    follow_walked_path(actor, person)
                    person.update(assisted=True, status="waiting", found_at_seconds=now, release_at=min(person["release_at"], now))
                    continue
            if not goal: continue
            if not actor.get("edge_id"):
                path = route(actor["node_id"], goal)
                if path is None:
                    if is_helper: actor["state"] = "blocked"
                    previous_wait = actor.pop('waiting_for_edge', None)
                    if previous_wait:
                        waiting_counts[previous_wait] = max(0, waiting_counts[previous_wait]-1)
                        invalidate_flow()
                    continue
                if is_helper: actor['state'] = 'approaching'
                if not path:
                    if is_helper and person.get("edge_id"):
                        if edges[person['edge_id']]['status']=='blocked':
                            actor['state']='blocked'
                            continue
                        path = [(person["edge_id"], person["edge_to"])]
                    elif not is_helper:
                        person.update(status="evacuated", evacuated_at_seconds=now, assembly_arrived_at_seconds=now)
                        if person["id"] in helpers: helpers[person["id"]]["state"] = "completed"
                        continue
                    else: continue
                eid, to = path[0]; edge = edges[eid]
                if is_helper and actor.get('purpose')=='household_visit' and not actor.get('cancelling') and zone_density(env, edge=edge) > visit_smoke_limit:
                    actor.update(state='blocked', risk_blocked=True)
                    continue
                actor.pop('risk_blocked', None)
                actor.pop("yielding_vehicle", None)
                if eid in reserved_roads:
                    actor.update(yielding_vehicle=reserved_roads[eid], waiting_for_edge=eid, congestion=100.)
                    actor["queue_seconds"] += dt
                    actor.setdefault("queued_at", now)
                    continue
                lanes = lane_count(edge)
                occupants = occupied[eid]
                lane = next((i for i in sorted(range(lanes), key=lambda lane: abs(lane-(lanes-1)/2)) if not any(a.get("lane") == i and (a["edge_from"] != actor["node_id"] or a["edge_progress"] < footprint(a)) for a in occupants)), None)
                if lane is None:
                    previous_wait = actor.get("waiting_for_edge")
                    if previous_wait != eid:
                        if previous_wait: waiting_counts[previous_wait] = max(0, waiting_counts[previous_wait]-1)
                        waiting_counts[eid] += 1
                        actor["waiting_for_edge"] = eid
                        invalidate_flow()
                    actor["queue_seconds"] += dt; actor["congestion"] = 100.; actor.setdefault("queued_at", now)
                    continue
                previous_wait = actor.pop("waiting_for_edge", None)
                if previous_wait:
                    waiting_counts[previous_wait] = max(0, waiting_counts[previous_wait]-1)
                actor.update(edge_id=eid, edge_from=actor["node_id"], edge_to=to, edge_progress=0., lane=lane, edge_started_at=now)
                actor.pop("queued_at", None)
                occupied[eid].append(actor)
                invalidate_flow()
            edge = edges[actor["edge_id"]]
            retreat = edge["status"] == "blocked"
            speed = 1.6 if is_helper else person.get('walking_speed', .8 if person["vulnerable"] else 1.3)*(1.2 if person["assisted"] else 1)
            if edge["kind"] == "stairs": speed *= .65
            lanes = lane_count(edge)
            actor["congestion"] = round(min(100., pressure(actor["edge_id"])*100))
            lateral_amplitude = abs(actor["lane"]-(lanes-1)/2)*.55
            # Bound actual 3-D displacement including curved lane transitions.
            speed /= math.sqrt(1+(math.pi*lateral_amplitude/edge["length"])**2)
            travel = speed*dt
            progress = max(0., actor["edge_progress"]-travel) if retreat else min(edge["length"], actor["edge_progress"]+travel)
            for other in occupied[actor["edge_id"]]:
                if other is actor or other.get("lane") != actor.get("lane"): continue
                if other["edge_from"] == actor["edge_from"]:
                    if not retreat and other["edge_progress"] > actor["edge_progress"]: progress = min(progress, max(actor["edge_progress"], other["edge_progress"]-footprint(other)))
                    if retreat and other["edge_progress"] < actor["edge_progress"]: progress = max(progress, min(actor["edge_progress"], other["edge_progress"]+footprint(actor)))
            if is_helper and actor.get('purpose')!='household_visit' and person.get("edge_id") == actor["edge_id"] and person["edge_from"] == actor["edge_from"]:
                progress = min(progress, person["edge_progress"])
            moved = abs(progress-actor["edge_progress"])
            if moved < travel*.5: actor["queue_seconds"] += dt; actor["congestion"] = 100.
            actor["travelled"] += moved; actor["edge_progress"] = progress
            a, b = nodes[actor["edge_from"]], nodes[actor["edge_to"]]
            ratio = progress/edge["length"]
            for key in ("x", "y", "height"): actor[key] = a[key]+(b[key]-a[key])*ratio
            # Parallel lanes have separate visible centre-lines; the offset
            # fades to zero at vertices, preserving continuity on every turn.
            lanes = lane_count(edge)
            offset = (actor["lane"]-(lanes-1)/2)*.55*math.sin(math.pi*ratio)
            horizontal = math.hypot(b["x"]-a["x"], b["y"]-a["y"])
            if horizontal > .01:
                actor["x"] += -(b["y"]-a["y"])/horizontal*offset
                actor["y"] += (b["x"]-a["x"])/horizontal*offset
            if not is_helper:
                actor["status"] = "moving"
                actor["indoor_stage"] = edge["kind"] if edge["kind"] in {"room", "corridor", "stairs", "door"} else "outdoor"
                actor["current_floor"] = (1+max(0,actor['height']-.18)/3.2 if actor['height']>0 else 0) if world.get('spatial_units',{}).get('height_mode')=='meters' else max(0, actor["height"]/1.92)
            else: actor["state"] = "approaching"
            if (retreat and progress <= .00001) or (not retreat and progress >= edge["length"]-.00001):
                actor["node_id"] = actor["edge_from"] if retreat else actor["edge_to"]
                occupied[actor["edge_id"]].remove(actor); actor["edge_id"] = None
                invalidate_flow()
                if not is_helper and nodes[actor["node_id"]]["kind"] == "door" and actor["node_id"].endswith(":door"):
                    actor.setdefault("building_exited_at_seconds", now+dt)
                if not is_helper and nodes[actor["node_id"]].get("is_exit"): actor.setdefault("exit_reached_at_seconds", now+dt)
            if not is_helper and person["id"] in helpers and helpers[person["id"]]["state"] == "escorting":
                follow_walked_path(helpers[person['id']], person, elapsed=now+dt)
        for actor in [*people, *helpers.values()]:
            record_motion(actor, now + dt)
        now += dt
    if checkpoint_out is not None and not strategy and now * 2 == int(now * 2):
        checkpoint_out.update(revision_id=ENGINE_REVISION, world_digest=digest(world),
            history_digest=digest(history[:index]), now=now, index=index,
            people=deepcopy(people), helpers=deepcopy(helpers), revision=revision,
            flow_revision=flow_revision, routes=[(list(key), deepcopy(value)) for key, value in route_cache.items()],
            occupied={eid: [a["id"] for a in actors] for eid, actors in occupied.items()}, waiting_counts=dict(waiting_counts),
            edge_statuses={eid: edge["status"] for eid, edge in edges.items()})
    fire, env = environment_at(elapsed)
    sync_doors()
    if flow_dirty:
        flow_revision += 1
        route_cache.clear()
    for person in people:
        path = suffix(person, destination(person))
        points = [{k: person[k] for k in ("x", "y", "height")}]
        remaining = 0.
        if person.get("edge_id"):
            end = person["edge_from"] if edges[person["edge_id"]]["status"] == "blocked" else person["edge_to"]
            points.append(nodes[end]); remaining += math.dist(xyz(person), xyz(nodes[end]))
        if path:
            for eid, to in path: points.append(nodes[to]); remaining += edges[eid]["length"]
        person.update(route_reachable=path is not None, route_points=points, route_edge_ids=([person["edge_id"]] if person.get("edge_id") else [])+[eid for eid, _ in path or []], current_edge_id=person.get("edge_id"), route_distance=remaining, remaining_seconds=round(remaining/person.get("walking_speed", .8 if person["vulnerable"] else 1.3)) if path is not None else 9999, estimated_seconds=round((remaining+person["travelled"])/1.3), progress=round(person["travelled"]/max(.01, person["travelled"]+remaining), 3), speed_factor=person["walking_speed"]/1.3 if "walking_speed" in person else .6 if person["vulnerable"] else 1.)
        if person["status"] == "evacuated": person["indoor_stage"] = "outdoor"
        person["last_location"] = nodes[person.get("edge_from") if person.get("edge_id") else person["node_id"]]["name"] + (" → "+nodes[person["edge_to"]]["name"] if person.get("edge_id") else "")
        helper = helpers.get(person["id"])
        person["behavior"] = "集合点已核验" if person["counted"] else "已到集合点，等待清点" if person["status"] == "evacuated" else "失联，等待搜索会合" if person["status"] == "missing" else "等待护送员入楼会合" if helper and helper["state"] in {"approaching", "blocked"} else "通道排队，前人通过后前进" if person["congestion"] else "所选集合点不可达，请改道" if not person["route_reachable"] else "等待通知" if now < person["release_at"] else "准备离开房间" if now < preparation_end(person) else "护送同行" if person["assisted"] else "沿连续通道撤离"
        if person.get('notification_confirmed_at') is not None and not person.get('forced_exit') and person['status']=='waiting':
            person['behavior']='已核实收到通知，等待总控安排撤离或重点接应'
        if person.get('awaiting_escort') and not person.get('edge_id') and person['status'] not in {'evacuated', 'missing'}:
            person['behavior'] = '已接到通知，等待护送批次或人工重新安排'
        if person.get("yielding_vehicle") and person.get("waiting_for_edge") in traffic_at(elapsed): person["behavior"] = "应急车辆通行管控，在路段入口等待放行"
    for helper in helpers.values():
        if helper.get('purpose') == 'household_visit':
            goal = visit_goal(helper)
            path = suffix(helper, goal)
            points = [{key:helper[key] for key in ('x','y','height')}]
            if helper.get('edge_id'):
                end = helper['edge_from'] if edges[helper['edge_id']]['status']=='blocked' else helper['edge_to']
                points.append(nodes[end])
            if path: points.extend(nodes[to] for _,to in path)
            helper.update(route_points=points, route_reachable=path is not None)
            helper['behavior'] = ('本次核查已结束' if helper['state']=='completed' else
                '已到户门，等待核查回执' if helper['state']=='at_door' else
                '撤回中，先走完当前通道再释放岗位' if helper.get('cancelling') else
                '前方烟气风险超出到户核查条件，请改用电话或调整处置' if helper.get('risk_blocked') else
                '到户通道受阻，请恢复通道或撤回核查' if path is None else
                '前方排队，等待通道释放' if helper.get('congestion',0)>55 else '沿楼梯与走廊前往户门')
            if path is None and helper['state'] not in {'completed','at_door'}: helper['state']='blocked'
            continue
        person = by_id[helper["resident_id"]]
        if helper["state"] in {"escorting", "completed"}:
            helper["route_points"] = [dict(zip(('x','y','height'),point)) for point in helper.get('escort_trail', [xyz(helper)])] + person["route_points"][1:]
            helper["route_reachable"] = person["route_reachable"]
            helper['behavior'] = '已护送到集合区域' if helper['state']=='completed' else '已会合，沿实际通道护送同行'
            continue
        goal = person.get("edge_from") if person.get("edge_id") else person["node_id"]
        path = suffix(helper, goal)
        if person.get('edge_id') and edges[person['edge_id']]['status']=='blocked' and not can_meet(helper, person, edges):
            path = None
        points = [{key: helper[key] for key in ("x", "y", "height")}]
        if helper.get("edge_id"):
            end = helper["edge_from"] if edges[helper["edge_id"]]["status"] == "blocked" else helper["edge_to"]
            points.append(nodes[end])
        if path:
            points.extend(nodes[to] for _, to in path)
        if path is not None:
            points.append({key: person[key] for key in ("x", "y", "height")})
        helper["route_points"] = points
        helper["route_reachable"] = path is not None
        helper['behavior'] = '前往会合的通道不可达，请恢复道路或安排其他出口' if path is None else '通道排队，等待前方人员通过' if helper.get('congestion',0)>55 else '正在沿通道前往居民所在位置'
        if path is None: helper['state'] = 'blocked'
    final_actors = [*people, *(h for h in helpers.values() if h["state"] in {"approaching", "blocked"})]
    occupied = defaultdict(list)
    waiting_counts = defaultdict(int)
    for actor in final_actors:
        if actor.get("edge_id"): occupied[actor["edge_id"]].append(actor)
        if actor.get("waiting_for_edge"): waiting_counts[actor["waiting_for_edge"]] += 1
    runtime_edges = {}
    for live_edge in graph["edges"]:
        source = edges[live_edge["id"]]
        mid = ((source["start"]["x"]+source["end"]["x"])/2, (source["start"]["y"]+source["end"]["y"])/2)
        smoke_risk = round(zone_density(env, edge=source)*100) if world.get('indoor_environment') else round(max(0, 1-math.dist(mid, (origin["x"], origin["y"]))/max(.01, fire["smoke_radius"]))*100) if fire["smoke_radius"] > 0 else 0
        if world.get('outdoor_smoke_domain') == 'exterior_v1' and source.get('kind') not in {'outdoor', 'assembly'}:
            smoke_risk = 0
        capacity = edge_capacity(source)
        occupancy, waiting = len(occupied[source["id"]]), waiting_counts[source["id"]]
        reserved_space = sum(footprint(actor)/.8 for actor in occupied[source['id']])
        density = min(100, round((reserved_space+waiting*.72)/capacity*100))
        status_penalty = 100 if source["status"] == "blocked" else 12 if source["status"] == "restricted" else 0
        risk_score = 100 if source["status"] == "blocked" else min(99, round(smoke_risk*.68+density*.32+status_penalty))
        flow_modifier = .58 if source["status"] == "restricted" else .72 if source.get("kind") == "stairs" else .82 if source.get("kind") in {"room", "door"} else 1.
        live_edge.update(status=source["status"], length=round(source["length"], 2), lane_count=lane_count(source), capacity_persons=capacity, live_occupancy=occupancy, waiting_count=waiting, density_percent=density, flow_capacity_per_second=round(max(.35, source["width_meters"]*1.15*flow_modifier), 2), smoke_risk=smoke_risk, risk_score=risk_score)
        runtime_edges[live_edge["id"]] = live_edge
    roads = {**world["road_network"], "edges": [dict(edge) for edge in world["road_network"]["edges"]]}
    roads["obstacles"] = obstacles
    for e in roads["edges"]:
        metrics = runtime_edges[e["id"]]
        e.update({key: metrics[key] for key in ("status", "lane_count", "capacity_persons", "live_occupancy", "waiting_count", "density_percent", "flow_capacity_per_second", "smoke_risk", "risk_score")})
        if metrics.get("geometry_blocked"):
            e.update(geometry_blocked=True, blocked_reason=metrics["blocked_reason"])
        e["reserved_by_vehicle"] = traffic_at(elapsed).get(e["id"])
    south = [e for e in roads["edges"] if "南" in e["name"]]
    env["response_staff"] = staff_projection(world, helpers, history)
    from app.services.community_training import project_community
    from types import SimpleNamespace
    community = project_community(world, [SimpleNamespace(**e) for e in history], people)
    if community:
        community['visits'] = [h for h in helpers.values() if h.get('purpose')=='household_visit']
        notices = {h['id']:h['notification_state'] for h in community['households']}
        for person in people:
            person['notification_state'] = notices.get(person.get('household_id'), 'unnotified')
    env.update(south_lane="blocked" if any(e["status"] == "blocked" for e in south) else "restricted" if any(e["status"] == "restricted" for e in south) else "open", visibility=max(8, round(100-fire["smoke_radius"]*1.8)), blockages=[{"x": (e["start"]["x"]+e["end"]["x"])/2, "y": (e["start"]["y"]+e["end"]["y"])/2, "target": e["name"], "road_edge_id": e["id"]} for e in roads["edges"] if e["status"] == "blocked"])
    if env.get('indoor'):
        from app.services.indoor_safety import project_door_safety
        env = {**env, 'indoor': project_door_safety(env['indoor'], world['indoor_environment'], people, list(helpers.values()))}
        env['visibility'] = min(zone['visibility'] for zone in env['indoor']['zones'])
    congested_edges = sorted((edge for edge in runtime_edges.values() if edge["density_percent"] >= 55), key=lambda edge: (-edge["density_percent"], -edge["waiting_count"], edge["id"]))
    return dict(community=community, elapsed_seconds=elapsed, fire=fire, environment=env, sensors={"temperature": fire["temperature"], "smoke_ppm": round(45+fire["smoke_radius"]*31), "alarm": fire["intensity"] >= 35}, residents=people, helpers=[h for h in helpers.values() if h.get('purpose')!='household_visit'], world=world, spatial_network=graph, road_network=roads, strategy=strategy or "live_commands", parallel_strategy=strategy, summary=dict(total=len(people), evacuated=sum(p["status"] == "evacuated" for p in people), counted=sum(p["counted"] for p in people), moving=sum(p["status"] == "moving" for p in people), vulnerable=sum(p["vulnerable"] for p in people), missing=sum(p["status"] == "missing" for p in people), smoke_exposed=sum(p["smoke_exposure"] > 5 for p in people), congested=sum(p["congestion"] > 55 for p in people), congested_edges=len(congested_edges), critical_edge=({key: congested_edges[0][key] for key in ("id", "name", "density_percent", "waiting_count")} if congested_edges else None), north_load=sum(p["exit"] == "north" for p in people), south_load=sum(p["exit"] == "south" for p in people)))
