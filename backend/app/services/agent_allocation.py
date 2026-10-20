"""Deterministic exit allocation on authoritative continuous-space routes.

Heuristic costs rank proposals only. The existing simulation, not these costs,
produces the 30-second evacuation, exposure and scoring forecasts.
"""
import math
from collections import Counter


def route_profile(person, resident, edges):
    ids = list(dict.fromkeys(person.get("route_edge_ids", [])))
    points = person.get("route_points", [])
    # A current blocked edge can be traversed backwards to retreat. The spatial
    # planner already validates that suffix; do not reject its first edge twice.
    reachable = bool(person.get("route_reachable"))
    speed = (.8 if resident.get("vulnerable") else 1.3) * (1.2 if resident.get("assisted") else 1)
    travel, smoke = 0., 0.
    for index, eid in enumerate(ids):
        edge = edges.get(eid, {})
        length = math.dist(tuple(points[index].get(k, 0) for k in ("x", "y", "height")),
                           tuple(points[index+1].get(k, 0) for k in ("x", "y", "height"))) if index + 1 < len(points) else edge.get("length", 0)
        seconds = length / (speed * (.65 if edge.get("kind") == "stairs" else 1))
        travel += seconds
        smoke += seconds * edge.get("smoke_risk", 0) / 100
    if not ids:
        travel = person.get("remaining_seconds", 0)
    return {"edges": ids, "reachable": reachable, "travel": travel,
            "smoke": smoke * (1.5 if resident.get("vulnerable") else 1),
            "peak_risk": max((edges.get(eid, {}).get("risk_score", 0) for eid in ids), default=0)}


def allocate_exits(routes, population, spatial_edges, selected_ids, preference="balanced"):
    """Compare a path/preference policy with risk- and shared-flow-aware allocation."""
    edges = {edge["id"]: edge for edge in spatial_edges}
    profiles = {pid: {exit: route_profile(routes[exit][pid], population[pid], edges) for exit in ("north", "south")}
                for pid in selected_ids}
    selected = set(selected_ids)
    # Selected waiters are replaced by proposed demand, not counted twice.
    external = Counter(p["waiting_for_edge"] for p in population.values()
                       if p["id"] not in selected and p.get("waiting_for_edge") and p.get("status") != "evacuated")
    selected_waiters = Counter(population[pid]["waiting_for_edge"] for pid in selected_ids if population[pid].get("waiting_for_edge"))
    for eid, edge in edges.items():
        if "waiting_count" in edge:
            external[eid] = max(0, edge["waiting_count"] - selected_waiters[eid])
    path_first = {}
    for index, pid in enumerate(selected_ids):
        path_first[pid] = preference if preference in {"north", "south"} else min(("north", "south"), key=lambda exit: (
            not profiles[pid][exit]["reachable"], profiles[pid][exit]["travel"], exit != ("north" if index % 2 == 0 else "south")))
    balanced, demand = {}, Counter()
    for pid in sorted(selected_ids, key=lambda pid: (not population[pid].get("vulnerable"), pid)):
        def cost(exit):
            profile = profiles[pid][exit]
            if not profile["reachable"]:
                return math.inf
            queue = max(((external[eid] + demand[eid]) / max(.35, edges.get(eid, {}).get("flow_capacity_per_second", .35))
                         for eid in profile["edges"]), default=0)
            return profile["travel"] + 3 * profile["smoke"] + 2 * queue
        chosen = min(("north", "south"), key=lambda exit: (cost(exit), exit != path_first[pid], exit))
        balanced[pid] = chosen
        if profiles[pid][chosen]["reachable"]:
            demand.update(profiles[pid][chosen]["edges"])
    assignments = [path_first, balanced]
    result = []
    for index, assignment in enumerate(assignments):
        load = Counter(eid for pid, exit in assignment.items() for eid in profiles[pid][exit]["edges"] if profiles[pid][exit]["reachable"])
        hotspots = sorted(load, key=lambda eid: (-(load[eid] + external[eid]) / max(.35, edges.get(eid, {}).get("flow_capacity_per_second", .35)),
                                               -edges.get(eid, {}).get("risk_score", 0), eid))[:3]
        result.append((assignment, {"rule": "path" if index == 0 else "risk_capacity",
            "description": "按指定出口分配；可达性仍需核对。" if index == 0 and preference != "balanced" else
                "优先选择较短通行时间的可达路线。" if index == 0 else
                "优先安排重点人员，综合行程、烟气风险和共享通道需求逐人分流；最终结果由30秒仿真核对。",
            "changed_residents": sum(assignment[pid] != path_first[pid] for pid in selected_ids),
            "same_allocation": path_first == balanced,
            "peak_risk": max((profiles[pid][exit]["peak_risk"] for pid, exit in assignment.items()), default=0),
            "bottlenecks": [{"edge_id": eid, "name": edges.get(eid, {}).get("name", eid),
                "assigned": load[eid], "waiting": external[eid],
                "flow_capacity": edges.get(eid, {}).get("flow_capacity_per_second", .35),
                "risk_score": edges.get(eid, {}).get("risk_score", 0),
                "resident_id": next(pid for pid, exit in assignment.items() if eid in profiles[pid][exit]["edges"])} for eid in hotspots]}))
    return result
