"""Conservative corridor interlock: clear pedestrians, reserve, pass, release."""
from bisect import bisect_right
from copy import deepcopy


class TrafficTimeline:
    def __init__(self, events):
        self.times, self.states = [-1], [{}]
        current = {}
        for event in sorted(events, key=lambda e: (e["elapsed_seconds"], e["sequence"])):
            kind, data, at = event["event_type"], event["payload"], event["elapsed_seconds"]
            key = data.get("vehicle_id")
            if kind in {"vehicle.dispatched", "vehicle.replanned"}:
                current.pop(key, None)
                if data.get("traffic_control") and data.get("can_apply"):
                    current[key] = {"edges": data["route_edge_ids"], "until": None if data.get("hold_for_pedestrians") else at + data["planned_duration_seconds"]}
            elif kind == "vehicle.traffic_released" and key in current:
                current[key] = {**current[key], "until": at + data["planned_duration_seconds"]}
            elif kind == "vehicle.cancelled": current.pop(key, None)
            else: continue
            self.times.append(at); self.states.append(deepcopy(current))

    def at(self, elapsed):
        state = self.states[bisect_right(self.times, elapsed) - 1]
        return {edge: key for key, value in state.items() if value["until"] is None or elapsed < value["until"] for edge in value["edges"]}


def protect_plan(plan, state, vehicle_id):
    plan = {**plan, "traffic_control": True}
    if plan["can_apply"] and plan["route_distance"] < .03:
        return {**plan, "can_apply": False, "hold_for_pedestrians": False, "yielding_people": 0,
                "notice": "车辆已经在该节点，请选择另一处道路节点；到场处置可在当前车辆面板直接预览。"}
    route = set(plan["route_edge_ids"])
    conflict = next((v for v in state["vehicles"] if v["id"] != vehicle_id and v["state"] in {"moving", "yielding"}
                     and route.intersection(v["route_edge_ids"])), None)
    if conflict:
        return {**plan, "can_apply": False, "notice": f"路线与{conflict['name']}正在使用的通道交叉，请待其通过后再调度。"}
    occupants = sum(e.get("live_occupancy", 0) for e in state["road_network"]["edges"] if e["id"] in route)
    return {**plan, "hold_for_pedestrians": occupants > 0, "yielding_people": occupants,
            "notice": plan["notice"] + (f" 通道内尚有 {occupants} 人，车辆将待其走出后出发，入口暂缓放行。" if occupants else " 行驶期间管控所经路段入口，到场后自动恢复人员通行。")}
