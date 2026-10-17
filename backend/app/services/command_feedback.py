"""Execution receipts derived from persisted commands and the actual live world."""


def commit_changes(session):
    """Commands and their domain events commit together; legacy calls still commit."""
    if session.info.get("drill_command_transaction"):
        session.flush()
    else:
        session.commit()


def command_feedback(events, simulation, robot, elapsed, drill_status):
    receipts = [e for e in events if e.event_type == "command.accepted"]
    people = {p["id"]: p for p in simulation["residents"]}
    queue = {t["id"]: t for t in (robot or {}).get("task_queue", [])}
    latest_assignment = {}
    for receipt in receipts:
        if receipt.payload["kind"] == "residents.assign":
            for resident_id in receipt.payload["arguments"].get("resident_ids", []):
                latest_assignment[resident_id] = max(receipt.sequence, latest_assignment.get(resident_id, -1))
    output = []
    # Reconcile every receipt: display limits must never freeze an old live task.
    for event in receipts:
        data = event.payload
        kind, payload = data["kind"], data["arguments"]
        status, progress, reason, remaining = "completed", 1., "现场状态已更新，关联事件已留存。", 0
        resident_ids = payload.get("resident_ids", []) if kind == "residents.assign" else [payload.get("resident_id")] if kind == "search.assign" else []
        selected = [people[p] for p in resident_ids if p in people]
        completed = sum(p["status"] == "evacuated" for p in selected)
        if selected:
            progress = sum(1 if p["status"] == "evacuated" else min(.99, p.get("progress", 0)) for p in selected) / len(selected)
            remaining = max((p.get("remaining_seconds", 0) or 0 for p in selected if p["status"] != "evacuated"), default=0)
            later_ids = {p["id"] for p in selected if latest_assignment.get(p["id"], -1) > event.sequence}
            blocked = [p for p in selected if p["status"] != "evacuated" and (p.get("route_reachable") is False or p["status"] == "missing")]
            if completed == len(selected):
                reason = f"{completed} 名居民已到集合点，请在清点区核验到场。"
            elif all(p["id"] in later_ids or p["status"] == "evacuated" for p in selected):
                status, reason, remaining = "superseded", "未到达人员已收到新的路线指令，请查看最新指令。", None
            elif blocked:
                status, reason, remaining = "blocked", f"{len(blocked)} 人暂不能继续：{blocked[0]['label']} · {blocked[0].get('behavior', '等待可用路线')}。", None
            else:
                status = "executing"
                waiting = next((p for p in selected if p["status"] != "evacuated"), selected[0])
                reason = f"已到 {completed}/{len(selected)} 人；{waiting['label']} · {waiting.get('behavior', '沿通道移动')}。"
            if status in {'executing','blocked'}:
                approaching = [h for h in simulation.get('helpers', []) if h.get('resident_id') in resident_ids and h['state'] in {'approaching','blocked'}]
                obstructed = next((h for h in approaching if h['state']=='blocked' or h.get('route_reachable') is False), None)
                if obstructed:
                    status, remaining = 'blocked', None
                    reason = f"{obstructed.get('responsible','护送员')}：{obstructed.get('behavior','前往会合的路线不可达')}。居民尚未完成会合。"
                elif approaching:
                    remaining = None  # Resident walking ETA excludes the helper's approach and queues.
                    reason = f"已到 {completed}/{len(selected)} 人；{approaching[0].get('responsible','护送员')}：{approaching[0].get('behavior','正前往目标会合')}。会合后共同撤离。"
            if kind == "search.assign" and status == "blocked":
                helper = next((h for h in simulation.get("helpers", []) if h["resident_id"] == payload["resident_id"]), None)
                if helper and helper["state"] == "approaching" and helper.get('route_reachable') is not False:
                    status, reason = "executing", "搜索员正在沿通道寻找目标，会合后共同撤离。"
        elif kind == "robot.command" and payload.get("command") == "move":
            task = next((queue[i] for i in data.get("event_ids", []) if i in queue), None)
            if task:
                status, progress = task["status"], task["progress"]
                remaining = max(0, task["ends_at_seconds"] - elapsed) if status not in {"blocked", "cancelled"} else None
                reason = {"queued": "前序任务尚未完成，到达后按队列继续。", "executing": "机器人正沿道路逐段前往目标。", "blocked": "当前目标不可达；恢复道路或取消该任务后重新指派。", "completed": "机器人已到达目标，可执行该点位的现场动作。", "cancelled": "任务已取消，后续队列已重新衔接。"}[status]
        elif kind == "vehicle.command" and payload.get("command") in {"spray", "load", "handover"}:
            action_id = next((e.payload.get("action_id") for e in events if e.id in data.get("event_ids", []) and e.event_type == "vehicle.action_started"), None)
            action = next((a for a in simulation.get("rescue_actions", []) if a["action_id"] == action_id), None)
            if action:
                status, progress, remaining, reason = action["status"], action["progress"], action["remaining_seconds"], action["reason"]
                resident_ids = [action["resident_id"]] if action.get("resident_id") else []
            else:
                status, progress, remaining, reason = "accepted", 0, None, "处置已受理，等待现场状态确认。"
        elif kind == "vehicle.command" and payload.get("command") in {"dispatch", "replan"}:
            vehicle = next((v for v in simulation.get("vehicles", []) if v["id"] == payload.get("vehicle_id")), None)
            mission_id = next((e.id if e.event_type == "vehicle.dispatched" else e.payload.get("mission_id") for e in events if e.id in data.get("event_ids", []) and e.event_type in {"vehicle.dispatched", "vehicle.replanned"}), None)
            mission = next((m for m in (vehicle or {}).get("missions", []) if m["id"] == mission_id), None)
            if mission:
                status, progress, remaining = mission["status"], mission["progress"], mission["remaining_seconds"]
                reason = vehicle["reason"] if vehicle["mission_id"] == mission_id else "历史行程已结束，当前车辆正在执行另一任务。"
        if drill_status == "ended" and status in {"executing", "queued", "blocked"}:
            status, reason, remaining = "unfinished", "演练已结束，该指令尚未完成；当前结果已冻结。", None
        elif drill_status == "paused" and status in {"executing", "queued"}:
            status, reason = "paused", "演练已暂停，保持当前位置；继续后恢复执行。"
        output.append({"id": data["command_id"], "kind": kind, "label": event.message, "actor": event.actor,
                       "accepted_at": event.elapsed_seconds, "status": status, "progress": round(progress, 3),
                       "reason": reason, "remaining_seconds": remaining, "resident_ids": resident_ids,
                       "event_ids": data.get("event_ids", []), "score_before": data.get("score_before"),
                       "score_after_acceptance": data.get("score_after_acceptance"),
                       "completed_count": completed, "selected_count": len(selected)})
    return list(reversed(output))
