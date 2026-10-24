"""Read-only execution projection. Receipts and spatial state are the evidence.

This module never submits commands or changes plan approval. Keep payloads bounded
even when a single step contains thousands of residents.
"""
from sqlalchemy import select

from app.models.operations import DrillCommand, DrillEvent


def coordination_view(run, data, steps):
    """Explain the actual orchestration using bounded, read-only observations.

    Each lane describes existing deterministic services, not a fabricated model
    conversation. An issue points to a resident so the UI can return to the same
    authoritative 3D scene without creating another floating inspector.
    """
    ids = set(run.scope.get("resident_ids", []))
    people = [p for p in data["simulation"]["residents"] if p["id"] in ids]
    outstanding = [p for p in people if p["status"] != "evacuated"]
    helpers = {h["resident_id"]: h for h in data["simulation"].get("helpers", [])}
    # Count the whole target population; per-step attention is only a six-person
    # display sample and must not become the supervisor's observation limit.
    attention = {}
    for person in people:
        helper = helpers.get(person["id"])
        arrived = person["status"] == "evacuated"
        attention[person["id"]] = {"id": person["id"], "label": person.get("label", person["id"]),
            "arrived": arrived, "blocked": not arrived and (person["status"] == "missing" or
                not person.get("route_reachable", True) or bool(helper and helper["state"] == "blocked")),
            "smoke_exposure": person.get("smoke_exposure", 0), "queue_seconds": person.get("queue_seconds", 0)}
    bottlenecks = {}
    spatial_edges = {e["id"]: e for e in data["simulation"].get("spatial_network", {}).get("edges", [])}
    for person in outstanding:
        edge_id = person.get("waiting_for_edge")
        if not edge_id:
            continue
        edge = spatial_edges.get(edge_id, {})
        group = bottlenecks.setdefault(edge_id, {"edge_id": edge_id,
            "name": edge.get("name") or edge_id, "waiting": 0,
            "resident_id": person["id"], "max_wait_seconds": 0})
        group["waiting"] += 1
        group["max_wait_seconds"] = max(group["max_wait_seconds"], round(person.get("queue_seconds", 0)))
    critical = sorted(attention.values(), key=lambda p: (not p["blocked"], -p["smoke_exposure"], -p["queue_seconds"]))
    robot = data.get("robot") or {}
    robot_steps = [s for s in steps if s.get("kind") == "robot.command"]
    completed = sum(s["status"] == "completed" for s in steps)
    stalled = [s for s in steps if s["execution"]["stalled"]]
    awaiting = run.status == "awaiting_approval"
    state = "paused" if data["status"] == "paused" else run.status
    issues = []
    for person in critical:
        if person["arrived"]:
            continue
        if person["blocked"] or person["smoke_exposure"] > 5:
            issues.append({"id": person["id"], "resident_id": person["id"],
                "label": person["label"], "severity": "danger" if person["blocked"] else "warning",
                "reason": "路线受阻，请定位后核对通道" if person["blocked"] else "累计烟气暴露超过阈值，请检查护送与出口安排"})
    case_pending = [t for t in data.get('tasks', []) if t['status'] != 'completed' and t['status'] != 'waiting'] if run.scope.get('include_case_tasks') else []
    blocked_ids = {person['id'] for person in attention.values() if person['blocked']}
    closed_door = next((door for door in data['simulation'].get('environment', {}).get('indoor', {}).get('doors', [])
                        if door['state'] == 'closed' and any(actor['kind'] == 'resident' and actor['id'] in blocked_ids
                                                            for actor in door.get('occupants', []))), None)
    if awaiting:
        next_action = {"kind": "review", "label": "核对方案后确认执行", "reason": "当前只完成预演，尚未授权下令。"}
    elif run.status == "needs_review":
        next_action = {"kind": "replan", "label": "重新比较未完成部分", "reason": run.reason}
    elif closed_door and run.status in {'executing', 'waiting'}:
        next_action = {'kind': 'indoor', 'label': '检查受阻房门', 'door_id': closed_door['id'],
                       'reason': closed_door['label']+'处于关闭状态，目标居民无法离开。请核对烟气与人员后决定是否开门。'}
    elif issues and issues[0]['severity'] == 'danger' and run.status in {'executing', 'waiting'}:
        next_action = {'kind': 'focus', 'label': '定位'+issues[0]['label'],
                       'resident_id': issues[0]['resident_id'], 'reason': issues[0]['reason']}
    elif case_pending:
        task = min(case_pending, key=lambda t: (not t.get('verification_ready'), t.get('remaining_seconds', 9999)))
        next_action = {'kind': 'missions', 'label': '处置：'+task['title'],
            'reason': '等待责任人核验；'+('；'.join(task.get('blockers', [])) or '请提交操作证据')}
    elif run.status == "awaiting_rollcall":
        next_action = {"kind": "rollcall", "label": "前往集合清点", "reason": "行动已完成，等待参演人员核验到场名单。"}
    elif issues:
        next_action = {"kind": "focus", "label": "定位" + issues[0]["label"],
            "resident_id": issues[0]["resident_id"], "reason": issues[0]["reason"]}
    elif stalled:
        step = stalled[0]
        next_action = {"kind": "robot" if step.get("kind") == "robot.command" else "focus",
            "label": "检查长时间未推进的步骤", "resident_id": next(iter(step.get("resident_ids", [])), None),
            "reason": step["reason"]}
    else:
        next_action = {"kind": "observe", "label": "观察执行回执" if outstanding else "查看完成依据",
            "reason": run.reason}
    return {"status": state, "at_seconds": data["elapsed_seconds"],
        "lanes": [
            {"id": "perception", "label": "现场感知", "state": "observing" if data["status"] == "running" else "paused",
             "detail": f"目标 {len(people)} 人，未到场 {len(outstanding)} 人；事件 {data['latest_event_sequence']}" + (f"；厨房分区 {len(data['simulation']['environment']['indoor']['zones'])} 个" if data['simulation'].get('environment', {}).get('indoor') else '')},
            {"id": "planning", "label": "疏散规划", "state": "review" if run.status == "needs_review" else "approval" if awaiting else "confirmed",
             "detail": f"版本 {run.revision}，待确认 {len(run.candidates)} 个方案" if awaiting else run.reason},
            {"id": "resources", "label": "资源协同", "state": "waiting" if any(s["status"] == "waiting" for s in steps) else "observing",
             "detail": f"护送与分流 {len(steps)-len(robot_steps)} 项；机器人 {sum(s['status']=='completed' for s in robot_steps)}/{len(robot_steps)} 项完成"},
            {"id": "supervision", "label": "执行监督", "state": "attention" if issues or stalled else "observing",
             "detail": f"已完成 {completed}/{len(steps)} 项；{len(issues)} 项人员风险，{len(stalled)} 项长时间未推进"},
        ], "issues": issues[:6], "issue_count": len(issues), "bottlenecks": sorted(bottlenecks.values(), key=lambda p: (-p["waiting"], -p["max_wait_seconds"]))[:4],
        "robot": {"included": bool(robot_steps or run.scope.get("robot_broadcast")),
            "state": robot.get("state"), "battery": robot.get("battery"), "reason": robot.get("reason"),
            "steps_completed": sum(s["status"] == "completed" for s in robot_steps), "steps_total": len(robot_steps)},
        "next_action": next_action}


def execution_view(session, run, data):
    simulation = data["simulation"]
    people = {p["id"]: p for p in simulation["residents"]}
    helpers = {h["resident_id"]: h for h in simulation.get("helpers", [])}
    edges = {e["id"]: e for e in simulation.get("spatial_network", {}).get("edges", [])}
    command_ids = [s["command_id"] for s in run.steps]
    receipts = {c.command_id: c for c in session.scalars(select(DrillCommand).where(
        DrillCommand.drill_session_id == run.drill_session_id,
        DrillCommand.command_id.in_(command_ids)))} if command_ids else {}
    event_ids = {eid for c in receipts.values() for eid in c.event_ids}
    evidence = {e.id: e for e in session.scalars(select(DrillEvent).where(
        DrillEvent.drill_session_id == run.drill_session_id, DrillEvent.id.in_(event_ids)))} if event_ids else {}
    steps = []
    for original in run.steps:
        step = dict(original)
        step.pop("progress_signature", None)
        receipt = receipts.get(step["command_id"])
        if receipt:
            step.update(status=receipt.status, progress=receipt.progress, reason=receipt.reason)
        selected = [people[pid] for pid in step.get("resident_ids", []) if pid in people]
        attention = []
        for person in selected:
            helper = helpers.get(person["id"])
            edge = edges.get(person.get("waiting_for_edge") or person.get("current_edge_id"))
            arrived = person["status"] == "evacuated"
            blocked = not arrived and (person["status"] == "missing" or not person.get("route_reachable", True)
                                      or bool(helper and helper["state"] == "blocked"))
            attention.append({"id": person["id"], "label": person["label"],
                "location": person.get("last_location", "位置待更新"), "behavior": person.get("behavior", "等待现场更新"),
                "arrived": arrived, "blocked": blocked, "counted": bool(person.get("counted")),
                "queue_seconds": round(person.get("queue_seconds", 0)),
                "smoke_exposure": round(person.get("smoke_exposure", 0), 1),
                "bottleneck": edge.get("name", edge["id"]) if edge else None,
                "staff_name": helper.get("staff_name") if helper else None,
                "responsible": helper.get("responsible") if helper else None,
                "escort_state": helper["state"] if helper else None})
        attention.sort(key=lambda p: (not p["blocked"], p["arrived"], -p["smoke_exposure"], -p["queue_seconds"], p["id"]))
        linked = sorted((evidence[eid] for eid in (receipt.event_ids if receipt else []) if eid in evidence), key=lambda e: e.sequence)
        step["execution"] = {"total": len(selected), "arrived": sum(p["arrived"] for p in attention),
            "blocked": sum(p["blocked"] for p in attention),
            "queued": sum(not p["arrived"] and people[p["id"]].get("congestion", 0) > 0 for p in attention),
            "attention": attention[:6], "remaining_details": max(0, len(attention) - 6),
            "evidence": [{"id": e.id, "sequence": e.sequence, "at_seconds": e.elapsed_seconds,
                          "message": e.message} for e in linked[-4:]],
            "command_recorded": receipt is not None,
            "idle_seconds": max(0, data["elapsed_seconds"] - step.get("last_progress_at", data["elapsed_seconds"])),
            "stalled": run.status in {"executing", "waiting"} and data["status"] == "running" and step.get("status") == "executing" and
                       data["elapsed_seconds"] - step.get("last_progress_at", data["elapsed_seconds"]) >= 45}
        steps.append(step)
    staff = simulation.get("environment", {}).get("response_staff", [])
    return {"steps": steps, "at_seconds": data["elapsed_seconds"],
            "event_sequence": data["latest_event_sequence"],
            "staff": [{key: p.get(key) for key in ("id", "name", "state", "resident_id", "responsible", "completed_count")} for p in staff],
            "coordination": coordination_view(run, data, steps)}
