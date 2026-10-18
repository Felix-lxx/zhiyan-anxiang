"""Bounded robot branch for an approved evacuation workflow.

Residents remain independent of this branch. Only robot broadcasting depends on
the matching movement receipt; no model decides arrival or resource ownership.
"""
from uuid import uuid4
import math
from sqlalchemy import select
from app.models.operations import DrillCommand, DrillEvent


def completed_broadcast(session, run):
    """Reuse only this plan's confirmed, position-matched domain evidence."""
    if run.scope.get("robot_broadcast_evidence"):
        return run.scope["robot_broadcast_evidence"]
    steps = [*run.steps, *(step for archive in run.evidence for step in archive.get("steps", []))]
    for step in steps:
        if step.get("kind") != "robot.command" or step["arguments"]["command"] != "broadcast":
            continue
        command = session.scalar(select(DrillCommand).where(DrillCommand.drill_session_id == run.drill_session_id, DrillCommand.command_id == step["command_id"]))
        if not command or command.status != "completed":
            continue
        for event in session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == run.drill_session_id,
                DrillEvent.id.in_(command.event_ids), DrillEvent.event_type == "robot.broadcast_completed")):
            target = step["target_position"]
            if math.dist((event.payload.get("x", -100), event.payload.get("y", -100)), (target["x"], target["y"])) <= .5:
                return event.id
    return None


def robot_support(operations, session, drill, data, scope):
    if not scope.get("robot_broadcast"):
        return None, []
    world = data["simulation"]["world"]
    building = next(b for b in world["objects"] if b["id"] == scope["robot_building_id"])
    target = building["entry"]
    robot = data.get("robot")
    info = {"target": building["name"] + "楼门广播点", "x": target["x"], "y": target["y"],
            "can_apply": False, "route_points": [], "route_edge_ids": [], "duration_seconds": None,
            "battery_required": 0, "notice": "本场没有可用机器人。"}
    if scope.get("robot_broadcast_evidence"):
        info.update(can_apply=True, duration_seconds=0, already_completed=True,
                    notice="本计划已完成该楼门广播，复用原始证据，不重复派遣或扣减电量。")
        return info, []
    if not robot:
        return info, []
    if any(t["status"] in {"executing", "queued", "blocked"} for t in robot.get("task_queue", [])):
        info["notice"] = "机器人已有未完成任务；请等待完成，或在原调度中取消后重新比较。"
        return info, []
    route, points, edges, distance, _ = operations.plan_robot_route(
        session, drill, (robot["x"], robot["y"]), (target["x"], target["y"]))
    required = max(1, round(distance / 18)) + 3
    reachable = len(points) >= 2 and "目标不可达" not in route
    enough = robot["battery"] >= required
    info.update(can_apply=reachable and enough, route_points=points, route_edge_ids=edges,
                duration_seconds=max(8, round(distance / 3.5)) if reachable else None,
                battery_required=required, battery_available=robot["battery"], route=route,
                notice="已检查楼体净距与道路通行；与居民撤离并行，到位后执行一次广播。" if reachable and enough
                else "当前楼体净距或道路状态不允许到达广播点；请检查地图、恢复通道或更换目标。" if not reachable else f"电量不足：当前 {robot['battery']}，预计至少需要 {required}。")
    move_id, broadcast_id = str(uuid4()), str(uuid4())
    steps = [{"id": move_id, "label": "机器人前往" + info["target"], "kind": "robot.command",
              "arguments": {"command": "move", "x": target["x"], "y": target["y"], "target": info["target"]},
              "depends_on": [], "resident_ids": [], "route_edge_ids": edges},
             {"id": broadcast_id, "label": "机器人到位广播", "kind": "robot.command",
              "arguments": {"command": "broadcast"}, "depends_on": [move_id], "resident_ids": [],
              "target_position": {"x": target["x"], "y": target["y"]}, "route_edge_ids": []}]
    return info, steps


def robot_precondition(step, data):
    """Recheck resource state immediately before submitting a new robot command."""
    robot = data.get("robot")
    if not robot:
        return "本场机器人不可用，请人工核对。"
    if step["arguments"]["command"] == "move":
        if any(t["status"] in {"executing", "queued", "blocked"} for t in robot.get("task_queue", [])):
            return "机器人已被其他任务占用，尚未追加或覆盖任务。"
        if robot["battery"] < step.get("battery_required", 0):
            return "机器人剩余电量已不足以完成到位和广播，请重新比较。"
    else:
        position = step["target_position"]
        if robot["state"] != "arrived" or math.dist((robot["x"], robot["y"]), (position["x"], position["y"])) > .5:
            return "机器人尚未在本计划的楼门广播点到位，未执行广播。"
        if robot["battery"] < 3:
            return "机器人电量不足，未执行广播。"
    return None
