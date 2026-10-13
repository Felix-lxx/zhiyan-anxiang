"""Versioned exercise inputs, frozen in the creation event (no legacy DB rewrite)."""
from copy import deepcopy
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import MapObject, RoadNode, RoadEdge, SceneVersion, DecisionPoint
from app.models.operations import DrillEvent
from app.models.tasks import DecisionTask


def frozen_world(session: Session, drill) -> dict | None:
    created = session.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "drill.created").order_by(DrillEvent.sequence))
    return deepcopy(created.payload.get("world")) if created else None


def capture_world(session: Session, version: SceneVersion, parameters_override: dict | None = None) -> dict:
    parameters = {**deepcopy(version.parameters), **deepcopy(parameters_override or {})}
    nodes = [{"id": n.id, "name": n.name, "x": n.x, "y": n.y, "is_exit": n.is_exit} for n in session.scalars(select(RoadNode).where(RoadNode.community_version_id == version.community_version_id))]
    by_id = {n["id"]: n for n in nodes}
    edges = []
    for edge in session.scalars(select(RoadEdge).where(RoadEdge.community_version_id == version.community_version_id)):
        if edge.start_node_id in by_id and edge.end_node_id in by_id:
            edges.append({"id": edge.id, "name": edge.name, "start_node_id": edge.start_node_id, "end_node_id": edge.end_node_id, "start": {k: by_id[edge.start_node_id][k] for k in ("x", "y")}, "end": {k: by_id[edge.end_node_id][k] for k in ("x", "y")}, "width_meters": edge.width_meters, "status": edge.status.value, "risk_score": 0, "blocked_by_event": False})
    objects = []
    for obj in session.scalars(select(MapObject).where(MapObject.community_version_id == version.community_version_id).order_by(MapObject.created_at)):
        x, y = float(obj.geometry.get("x", 50)), float(obj.geometry.get("y", 50))
        entry = min(nodes, key=lambda n: math.dist((x, y), (n["x"], n["y"]))) if nodes else {"x": x, "y": y}
        objects.append({"id": obj.id, "name": obj.name, "type": obj.object_type.value, "x": x, "y": y, "entry": {"x": entry["x"], "y": entry["y"]}, "width": max(2, min(20, float(obj.properties.get("width", 5)))), "depth": max(2, min(20, float(obj.properties.get("depth", 3)))), "floors": max(1, min(20, int(obj.properties.get("floors", 6)))), "properties": deepcopy(obj.properties)})
    source = next((o for o in objects if o["id"] == parameters.get("fire_source_object_id")), next((o for o in objects if o["type"] == "charging_shed"), {"x": 66, "y": 43, "entry": {"x": 68, "y": 44}}))
    buildings = [o for o in objects if o["type"] == "building"]
    home = min(buildings, key=lambda o: math.dist((source["x"], source["y"]), (o["x"], o["y"]))) if buildings else source
    station = next((o for o in objects if o["type"] == "micro_fire_station"), home)
    count = max(1, min(1000, int(parameters.get("resident_count", 18))))
    residents = [{"id": f"resident-{i + 1}", "label": f"居民 {i + 1:02d}", "vulnerable": i in {2, 7, 14}, "building_id": home.get("id"), "x": home["entry"]["x"] + (i % 5 - 2) * .28, "y": home["entry"]["y"] + ((i // 5) % 12 - 5.5) * .25} for i in range(count)]
    tasks = []
    # An explicitly schematic indoor model. Only newly created worlds opt in;
    # existing frozen worlds retain their original replay behaviour.
    for i, resident in enumerate(residents):
        floor = i % home.get("floors", 1) + 1
        resident.update(floor=floor, indoor_stage="room", current_floor=float(floor),
                        indoor_remaining=float(floor * 6), preparation_seconds=3 + i % 7)
    for task in session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id == version.id).order_by(DecisionTask.created_at)):
        point = session.get(DecisionPoint, task.decision_point_id)
        kind = "power_off" if "断电" in task.title or "切断" in task.title else "broadcast" if "广播" in task.title else "escort" if "重点" in task.title else "manual"
        target = source if kind == "power_off" else home
        tasks.append({"id": task.id, "title": task.title, "target": task.target, "kind": kind, "responsible_role": "应急指挥人员" if kind == "broadcast" else "物业/网格员" if kind in {"power_off", "escort"} else point.responsible_role if point else "物业/网格员", "deadline_seconds": task.deadline_seconds, "duration_seconds": 8 if kind == "power_off" else 3, "target_object_id": target.get("id"), "target_position": target["entry"], "trigger": "alarm_confirmed", "steps": ["接收任务并核对目标", "到达目标位置（演练回执）", "完成处置并提交文字证据"]})
    from app.services.spatial_world import add_spatial_layout
    return add_spatial_layout({"scene_version_id": version.id, "community_version_id": version.community_version_id, "parameters": parameters, "objects": objects, "residents": residents, "fire_origin": {"x": source["x"], "y": source["y"]}, "robot_origin": station["entry"], "inspection_target": source["entry"], "broadcast_target": home["entry"], "tasks": tasks, "road_network": {"nodes": nodes, "edges": edges}}, home)


def projected_tasks(world: dict, events: list, elapsed: int, simulation: dict, robot: dict | None) -> list[dict]:
    confirmed = next((e.elapsed_seconds for e in events if e.event_type == "robot.alarm_confirmed"), None)
    result = []
    for source in world["tasks"]:
        history = [e for e in events if e.payload.get("task_id") == source["id"]]
        assigned = next((e for e in reversed(history) if e.event_type == "task.assigned"), None)
        accepted = next((e for e in history if e.event_type == "task.accepted"), None)
        arrived = next((e for e in history if e.event_type == "task.arrived"), None)
        done = next((e for e in history if e.event_type == "task.completed"), None)
        remaining = source["deadline_seconds"] - max(0, elapsed - (confirmed or 0))
        state = "completed" if done else "waiting" if confirmed is None else "verifying" if arrived else "executing" if accepted else "pending"
        blockers = []
        if source["kind"] == "broadcast" and not any(e.event_type == "robot.broadcast_completed" and math.dist((e.payload.get("x", -100), e.payload.get("y", -100)), (source["target_position"]["x"], source["target_position"]["y"])) <= 3 for e in events):
            blockers.append("请先指派机器人到此入口并完成广播")
        if source["kind"] == "escort" and any(p["vulnerable"] and (p["status"] != "evacuated" or not p.get("assisted")) for p in simulation["residents"]):
            blockers.append("重点人员尚未全部在护送下到达集合点")
        if not arrived:
            blockers.append("请先接收任务并回执到位")
        elif elapsed - arrived.elapsed_seconds < source["duration_seconds"]:
            blockers.append(f"处置还需 {source['duration_seconds'] - (elapsed - arrived.elapsed_seconds)} 秒")
        owner = accepted or assigned
        result.append({**source, "status": state, "overdue": confirmed is not None and remaining < 0 and not done, "remaining_seconds": max(0, remaining), "assignee": owner.actor if owner else None, "assignee_id": owner.payload.get("participant_id") if owner else None, "assignment_locked": accepted is not None, "blockers": blockers, "can_submit": bool(arrived and not blockers and not done), "evidence": done.payload.get("evidence") if done else None, "completed_at": done.elapsed_seconds if done else None})
    return result
