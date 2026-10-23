"""Timed on-scene actions and patient custody, derived from the event ledger."""
from copy import deepcopy
import math
from app.services.drill_simulation import clear_segment
from app.services.vehicle_dispatch import plan_vehicle, vehicle_runtime

ACTION_LABELS = {"spray": "喷水压制", "load": "接近并上车", "handover": "出口医疗移交"}


def project_rescue_state(world, events, elapsed, simulation):
    """One read-only projection for configuration preview, live drills and branches."""
    state = rescue_projection(world, events, elapsed, vehicle_runtime(world, events, elapsed), simulation)
    state["rescue_projection_version"] = 1
    state["navigation_geometry_version"] = 1
    for vehicle in state["vehicles"]:
        if vehicle["state"] == "yielding":
            occupants = [p for p in state["residents"] if p.get("current_edge_id") in vehicle["route_edge_ids"]]
            helpers = [h for h in state.get("helpers", []) if h.get("edge_id") in vehicle["route_edge_ids"]]
            vehicle["waiting_people"] = len(occupants) + len(helpers)
            names = "、".join(p["label"] for p in occupants[:3])
            vehicle["reason"] = f"通道内还有 {vehicle['waiting_people']} 人" + (f"（{names}）" if names else "") + "；入口已暂停放行，清空后自动出发。"
            if any(p["status"] == "missing" for p in occupants):
                vehicle["reason"] += "其中有失联人员，请先安排搜索会合，或取消行程后改选目标。"
        vehicle["service_options"] = {action: action_plan(world, state, vehicle, action) for action in (["spray"] if vehicle["kind"] == "firetruck" else ["handover"])}
    state["transfer_candidates"] = [{"id": p["id"], "label": p["label"], "exit": p.get("exit"), "eligible": bool(p.get("counted")),
                                     "reason": "已核验，可以接运" if p.get("counted") else "先在集合点完成清点"}
                                    for p in state["residents"] if p["status"] == "evacuated" and not p.get("medical_transfer") and (p["vulnerable"] or p.get("smoke_exposure", 0) > 5)]
    return state


def rescue_projection(world, events, elapsed, vehicles, simulation):
    vehicles = deepcopy(vehicles)
    history = sorted((e for e in events if e.elapsed_seconds <= elapsed), key=lambda e: (e.elapsed_seconds, e.sequence))
    ends = {e.payload.get("action_id"): e for e in history if e.event_type in {"vehicle.action_completed", "vehicle.action_stopped"}}
    actions, transfers = [], {}
    fleet = {v["id"]: v for v in vehicles}
    for vehicle in vehicles: vehicle.update(service=None, passenger=None, rescue_actions=[])
    for event in history:
        if event.event_type != "vehicle.action_started": continue
        data = event.payload; vehicle = fleet.get(data["vehicle_id"])
        if not vehicle: continue
        end = ends.get(data["action_id"])
        duration = data["duration_seconds"]
        stop_at = end.elapsed_seconds if end else elapsed
        progress = min(1., max(0., (stop_at - event.elapsed_seconds) / max(1, duration)))
        status = "completed" if end and end.event_type.endswith("completed") else "cancelled" if end else "executing"
        action = {**deepcopy(data), "id": data["action_id"], "label": ACTION_LABELS[data["action"]], "status": status, "progress": progress,
                  "starts_at_seconds": event.elapsed_seconds, "ends_at_seconds": event.elapsed_seconds + duration,
                  "remaining_seconds": max(0, event.elapsed_seconds + duration - elapsed) if not end else 0,
                  "reason": end.message if end else f"{ACTION_LABELS[data['action']]}进行中"}
        actions.append(action); vehicle["rescue_actions"].append(action)
        if not end: vehicle["service"] = action
        if data["action"] == "load" and status != "cancelled":
            phase = "onboard" if status == "completed" else "pickup" if elapsed - event.elapsed_seconds < data.get("approach_seconds", 0) else "loading"
            if status == "executing":
                action["reason"] = "担架组正前往集合点接人" if phase == "pickup" else "正在车边完成装载交接" if elapsed >= action["ends_at_seconds"] - 8 else "担架组正沿集合通道返回救护车"
            transfers[data["resident_id"]] = {"phase": phase, "vehicle_id": vehicle["id"],
                                              "resident_id": data["resident_id"], "label": data["resident_label"], "action": action}
            if status == "completed":
                vehicle["passenger"] = {"id": data["resident_id"], "label": data["resident_label"], "pickup_node_id": data["pickup_node_id"]}
        elif data["action"] == "handover" and status != "cancelled":
            transfers[data["resident_id"]] = {"phase": "delivered" if status == "completed" else "handing_over", "vehicle_id": vehicle["id"], "resident_id": data["resident_id"],
                                              "label": data["resident_label"], "position": data["position"], "action": action}
            if status == "completed": vehicle["passenger"] = None
    # The walker checkpoint remains untouched; custody is a presentation projection
    # over residents already evacuated and counted at the assembly point.
    residents = []
    for resident in simulation["residents"]:
        transfer = transfers.get(resident["id"])
        if not transfer: residents.append(resident); continue
        person = {**resident, "medical_transfer": {k: v for k, v in transfer.items() if k != "action"}, "node_id": None, "current_edge_id": None}
        vehicle = fleet[transfer["vehicle_id"]]
        if transfer["phase"] == "pickup":
            person.update(node_id=resident.get("node_id"), behavior="在集合点等待担架组到达", last_location="集合点接运位置")
        elif transfer["phase"] == "loading":
            action = transfer["action"]
            approach = action.get("approach_seconds", 0)
            person.update(point_on_route(action["pickup_points"], min(1., max(0., (elapsed - action["starts_at_seconds"] - approach) / max(1, action["duration_seconds"] - approach - 8)))))
            person.update(route_points=action["pickup_points"], behavior="担架组沿集合通道接近救护车，上车后再安排出口", last_location="集合点至救护车接运通道")
        elif transfer["phase"] == "onboard":
            person.update(x=vehicle["x"], y=vehicle["y"], height=0, route_points=vehicle["route_points"], behavior="已在救护车内，等待出口医疗移交", last_location=vehicle["name"])
        elif transfer["phase"] == "handing_over":
            points = [{"x": vehicle["x"], "y": vehicle["y"]}, transfer["position"]]
            person.update(point_on_route(points, transfer["action"]["progress"]))
            person.update(route_points=points, behavior="正在出口卸载并办理医疗移交", last_location="出口医疗接应点")
        else:
            person.update(**transfer["position"], height=0, route_points=[], behavior="已完成出口医疗移交", last_location="出口医疗接应点")
        residents.append(person)
    for vehicle in vehicles:
        vehicle["rescue_action_count"] = len(vehicle["rescue_actions"])
        vehicle["rescue_actions"] = vehicle["rescue_actions"][-6:]
    return {**simulation, "vehicles": vehicles, "residents": residents, "rescue_actions": actions,
            "medical_transfers": [{k: v for k, v in t.items() if k != "action"} for t in transfers.values()]}


def point_on_route(points, fraction):
    if not points: return {}
    lengths = [math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * fraction
    for a, b, length in zip(points, points[1:], lengths):
        if remaining <= length:
            ratio = remaining / max(.0001, length)
            return {"x": a["x"] + (b["x"] - a["x"]) * ratio, "y": a["y"] + (b["y"] - a["y"]) * ratio, "height": 0}
        remaining -= length
    return {"x": points[-1]["x"], "y": points[-1]["y"], "height": 0}


def action_plan(world, state, vehicle, action, resident_id=None):
    """Return the same blockers to both UI and authoritative command validation."""
    base = {"action": action, "can_apply": False, "notice": "", "duration_seconds": 0}
    def denied(message): return {**base, "notice": message}
    if not world or world.get("schema_version", 0) < 3: return denied("请在连续空间场次中使用到场处置。")
    if vehicle["state"] not in {"idle", "arrived"}: return denied("请等待车辆停稳后执行到场处置。")
    if vehicle.get("service"): return denied("当前处置尚未结束，请先停止或等待完成。")
    if action == "spray":
        if world.get('indoor_environment'): return denied('厨房位于楼内，当前消防车仅支持室外直达喷水；请完成燃气切断与室内疏散任务。')
        if vehicle["kind"] != "firetruck": return denied("喷水任务需要消防车。")
        if state["environment"]["east_hydrant"] == "failed": return denied("水源失效，无法供水。请在场景中准备可用水源。")
        if state["fire"]["intensity"] <= 0: return denied("当前火势已压制，无需重复喷水。")
        obstacles = [o for o in world["objects"] if o["type"] == "building"]
        origin = world["fire_origin"]; position = (vehicle["x"], vehicle["y"])
        water = [o for o in world["objects"] if o["type"] == "fire_hydrant" and o.get("properties", {}).get("status") not in {"failed", "faulty"}
                 and math.dist(position, (o["x"], o["y"])) <= 25 and clear_segment(position, (o["x"], o["y"]), obstacles)]
        if not water: return denied("附近没有可连接的水源；请驶至距消火栓 25 个场景单位内且水带不穿楼的位置。")
        if math.dist(position, (origin["x"], origin["y"])) > 25 or not clear_segment(position, (origin["x"], origin["y"]), obstacles):
            return denied("火点超出射程或中间有楼栋遮挡，请调整停靠节点。")
        hydrant = min(water, key=lambda o: math.dist(position, (o["x"], o["y"])))
        return {**base, "can_apply": True, "duration_seconds": 45, "target": origin, "water_source": {k: hydrant[k] for k in ("id", "name", "x", "y")}, "notice": "连接水源后连续喷水 45 秒，可提前停止；火势和烟气随有效供水时间下降。"}
    if vehicle["kind"] != "ambulance": return denied("接运任务需要救护车。")
    if action == "handover":
        passenger = vehicle.get("passenger")
        if not passenger: return denied("车内没有待移交人员。")
        node = next((n for n in state["road_network"]["nodes"] if n["is_exit"] and math.dist((n["x"], n["y"]), (vehicle["x"], vehicle["y"])) < .1), None)
        if not node: return denied("请先将车内人员送到道路出口的医疗接应点。")
        if node["id"] == passenger["pickup_node_id"]:
            return denied("尚未完成转运，请先驶往另一出口的医疗接应点。")
        return {**base, "can_apply": True, "duration_seconds": 8, "resident_id": passenger["id"], "resident_label": passenger["label"], "position": {"x": vehicle["x"] + 1.5, "y": vehicle["y"]}, "notice": "完成 8 秒医疗移交后解除车内人员占用，并生成交接证据。"}
    if vehicle.get("passenger"): return denied("车内已有人员，请先完成移交。")
    person = next((p for p in state["residents"] if p["id"] == resident_id), None)
    if not person: return denied("请选择集合点已核验、需要接运的人员。")
    if person["status"] != "evacuated" or not person.get("counted"): return denied("该居民尚未到集合点完成清点，不能直接装车。")
    if person.get("medical_transfer"): return denied("该居民已在接运流程中，不能重复接运。")
    if not person["vulnerable"] and person.get("smoke_exposure", 0) <= 5: return denied("请优先选择重点人员或烟气暴露超过 5 的居民。")
    graph = state["spatial_network"]
    target = next((n for n in graph["nodes"] if n["kind"] == "outdoor" and math.dist((n["x"], n["y"]), (vehicle["x"], vehicle["y"])) < .1), None)
    if not target: return denied("请将救护车停到道路节点再接运。")
    # Use only assembly connectors, never send the stretcher through a building
    # or across a live carriageway to reach a distant ambulance.
    network = {"nodes": graph["nodes"], "edges": [e for e in graph["edges"] if e["kind"] == "assembly"]}
    route = plan_vehicle(network, {**person, "minimum_width": .4, "speed": .8, "current_edge_id": None}, target["id"])
    if not route["can_apply"]: return denied("救护车不在该集合点对应出口，请先驶至同侧出口节点。")
    return {**base, "can_apply": True, "duration_seconds": route["planned_duration_seconds"] * 2 + 8, "approach_seconds": route["planned_duration_seconds"],
            "resident_id": person["id"], "resident_label": person["label"], "pickup_node_id": target["id"], "pickup_points": route["route_points"],
            "notice": "担架组沿集合通道到车边，再完成 8 秒装载；之后安排驶往出口并移交。"}
