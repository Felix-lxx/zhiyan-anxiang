"""Bounded robot branch for an approved evacuation workflow.

Residents remain independent of this branch. Only robot broadcasting depends on
the matching movement receipt; no model decides arrival or resource ownership.
"""
from uuid import uuid4
from copy import deepcopy
import math
from sqlalchemy import select
from app.models.operations import DrillCommand, DrillEvent


def completed_broadcast(session, run):
    """Reuse only this plan's confirmed, position-matched domain evidence."""
    if run.scope.get("robot_broadcast_evidence"):
        return run.scope["robot_broadcast_evidence"]
    steps = [*run.steps, *(step for archive in run.evidence for step in archive.get("steps", []))]
    broadcasts = [step for step in steps if step.get("kind") == "robot.command" and step.get("arguments", {}).get("command") == "broadcast"]
    evidence = []
    for step in broadcasts:
        command = session.scalar(select(DrillCommand).where(DrillCommand.drill_session_id == run.drill_session_id, DrillCommand.command_id == step["command_id"]))
        if not command or command.status != "completed":
            return None
        matched = None
        for event in session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == run.drill_session_id,
                DrillEvent.id.in_(command.event_ids), DrillEvent.event_type == "robot.broadcast_completed")):
            target = step["target_position"]
            if math.dist((event.payload.get("x", -100), event.payload.get("y", -100)), (target["x"], target["y"])) <= .5:
                matched = event.id
                break
        if not matched:
            return None
        evidence.append(matched)
    return evidence[-1] if broadcasts and len(evidence) == len(broadcasts) else None


def owned_steps(run):
    """Keep durable ownership across revisions, not just the visible step list."""
    if run is None:
        return []
    return [*run.steps, *(step for archive in reversed(run.evidence) for step in archive.get("steps", []))]


def remaining_robot_route(task, data):
    """Display only the untraversed polyline; retain every upcoming road corner."""
    if task["status"] == "completed":
        return []
    points = task["route_points"]
    robot = data["robot"]
    if len(points) < 2:
        return points
    lengths = [math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(points, points[1:])]
    progress = max(0, min(1, (data["elapsed_seconds"] - task["starts_at_seconds"]) / max(1, task["planned_duration_seconds"])))
    distance = sum(lengths) * progress
    for index, length in enumerate(lengths):
        if distance <= length or index == len(lengths) - 1:
            return [{"x": robot["x"], "y": robot["y"]}, *deepcopy(points[index + 1:])]
        distance -= length
    return []


def _reuse_robot(session, drill, data, target, run, info):
    robot = data["robot"]
    pending = [t for t in robot.get("task_queue", []) if t["status"] in {"executing", "queued", "blocked"}]
    steps = owned_steps(run)
    for step in steps:
        args = step.get("arguments", {})
        if step.get("kind") != "robot.command" or args.get("command") != "move":
            continue
        if math.dist((args.get("x", -100), args.get("y", -100)), (target["x"], target["y"])) > .5:
            continue
        receipt = session.scalar(select(DrillCommand).where(DrillCommand.drill_session_id == drill.id,
            DrillCommand.command_id == step.get("command_id")))
        if not receipt or receipt.kind != "robot.command" or receipt.command_args != args or receipt.status in {"cancelled", "superseded", "failed", "unfinished"}:
            continue
        # A matching coordinate is not ownership: only this plan's durable move
        # receipt can authorize reuse, and any foreign queued job prevents it.
        task = next((t for t in robot.get("task_queue", []) if t["id"] in receipt.event_ids), None)
        if not task or task["status"] == "cancelled" or any(t["id"] != task["id"] for t in pending):
            continue
        broadcast = next((s for s in steps if s.get("kind") == "robot.command"
            and s.get("arguments", {}).get("command") == "broadcast" and step["id"] in s.get("depends_on", [])), None)
        if not broadcast:
            continue
        arrived = task["status"] == "completed" and robot["state"] == "arrived" and math.dist(
            (robot["x"], robot["y"]), (target["x"], target["y"])) <= .5
        if task["status"] == "completed" and not arrived:
            continue
        reachable = task["status"] != "blocked"
        enough = robot["battery"] >= 3  # Movement was already charged on acceptance.
        info.update(can_apply=reachable and enough, reusing_task=True, already_arrived=arrived,
            route_points=remaining_robot_route(task, data), route_edge_ids=task["route_edge_ids"],
            duration_seconds=max(0, task["ends_at_seconds"] - data["elapsed_seconds"]) if reachable else None,
            battery_required=3, battery_available=robot["battery"], route=robot.get("route", []),
            notice="沿用本计划已到位的机器人，只执行尚未完成的广播。" if arrived and enough else
                "沿用本计划正在执行的移动任务，不重新排队或重复扣减移动电量；到位后继续广播。" if reachable and enough else
                "原机器人任务仍受阻，请先恢复通道或人工调整机器人，再重新比较。" if not reachable else "机器人剩余电量不足以完成广播。")
        return [deepcopy(step), deepcopy(broadcast)]
    return None


def robot_support(operations, session, drill, data, scope, run=None):
    if not scope.get("robot_broadcast"):
        return None, []
    world = data["simulation"]["world"]
    building_ids = scope.get("robot_building_ids") or ([scope.get("robot_building_id")] if scope.get("robot_building_id") else [])
    building_by_id = {item["id"]: item for item in world["objects"] if item["type"] == "building"}
    buildings = [building_by_id[key] for key in building_ids if key in building_by_id]
    target = buildings[0]["entry"] if buildings else {"x": 0, "y": 0}
    robot = data.get("robot")
    target_label = buildings[0]["name"] + "楼门广播点" if len(buildings) == 1 else "依次广播：" + "、".join(item["name"] for item in buildings)
    info = {"target": target_label, "target_count": len(buildings), "x": target["x"], "y": target["y"],
            "can_apply": False, "route_points": [], "route_edge_ids": [], "duration_seconds": None,
            "battery_required": 0, "notice": "本场没有可用机器人。"}
    if not buildings:
        info["notice"] = "目标居民没有可定位的楼栋入口，不能安排楼门广播。"
        return info, []
    if scope.get("robot_broadcast_evidence") and len(buildings) == 1:
        info.update(can_apply=True, duration_seconds=0, already_completed=True,
                    notice="本计划已完成该楼门广播，复用原始证据，不重复派遣或扣减电量。")
        return info, []
    if not robot:
        return info, []
    if not any(e['event_type'] == 'robot.inspection_started' for e in data.get('events', [])):
        info['notice'] = '请先开始演练并完成自动火情巡检，再批准楼门广播，避免占用尚未启动的巡检资源。'
        return info, []
    if len(buildings) == 1:
        reused = _reuse_robot(session, drill, data, target, run, info)
        if reused is not None:
            return info, reused
    if any(t["status"] in {"executing", "queued", "blocked"} for t in robot.get("task_queue", [])):
        info["notice"] = "机器人已有未完成任务；请等待完成，或在原调度中取消后重新比较。"
        return info, []
    cursor = (robot["x"], robot["y"])
    all_points, all_edges, all_route, steps = [], [], [], []
    total_required = total_duration = 0
    reachable = True
    previous_broadcast = None
    for building in buildings:
        entry = building["entry"]
        route, points, edges, distance, _ = operations.plan_robot_route(session, drill, cursor, (entry["x"], entry["y"]))
        segment_reachable = len(points) >= 2 and "目标不可达" not in route
        reachable = reachable and segment_reachable
        move_energy = max(1, round(distance / 18))
        segment_duration = max(8, round(distance / 3.5)) if segment_reachable else 0
        total_required += move_energy + 3
        total_duration += segment_duration
        all_points.extend(points if not all_points else points[1:])
        all_edges.extend(edge for edge in edges if edge not in all_edges)
        all_route.extend(route)
        move_id, broadcast_id = str(uuid4()), str(uuid4())
        label = building["name"] + "楼门广播点"
        steps.extend([
            {"id": move_id, "label": "机器人前往" + label, "kind": "robot.command",
             "arguments": {"command": "move", "x": entry["x"], "y": entry["y"], "target": label},
             "depends_on": [previous_broadcast] if previous_broadcast else [], "resident_ids": [],
             "route_edge_ids": edges, "battery_required": move_energy + 3},
            {"id": broadcast_id, "label": building["name"] + "楼门到位广播", "kind": "robot.command",
             "arguments": {"command": "broadcast"}, "depends_on": [move_id], "resident_ids": [],
             "target_position": {"x": entry["x"], "y": entry["y"]}, "route_edge_ids": [], "battery_required": 3},
        ])
        previous_broadcast = broadcast_id
        cursor = (entry["x"], entry["y"])
    enough = robot["battery"] >= total_required
    final_target = buildings[-1]["entry"]
    info.update(can_apply=reachable and enough, x=final_target["x"], y=final_target["y"],
                route_points=all_points, route_edge_ids=all_edges,
                duration_seconds=total_duration if reachable else None,
                battery_required=total_required, battery_available=robot["battery"], route=all_route,
                notice=(f"已拆分为 {len(buildings)} 个楼门的顺序广播任务；居民撤离并行，机器人按到位回执逐栋执行。"
                        if len(buildings) > 1 and reachable and enough else
                        "已检查楼体净距与道路通行；与居民撤离并行，到位后执行一次广播。" if reachable and enough else
                        "至少一个楼门无法通过当前道路到达；请检查地图、恢复通道或缩小目标范围。" if not reachable else
                        f"电量不足：当前 {robot['battery']}，连续广播预计至少需要 {total_required}。"))
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
