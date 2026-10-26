"""Read-only training guidance derived from the same state used by the scene.

No clock advancement, commands, score changes or database writes belong here.
The briefing is frozen for new runs; old runs get a labelled compatibility view.
"""
from copy import deepcopy


def build_briefing(world: dict) -> dict:
    people = world.get("residents", [])
    kitchen = world.get("parameters", {}).get("fire_source_type") == "kitchen"
    source = world.get("fire_source", {})
    address = source.get("label") or source.get("name") or ("住宅厨房" if kitchen else "充电棚")
    floor = source.get("floor") or world.get("parameters", {}).get("fire_floor")
    if kitchen and floor and not source.get("name"):
        address = f"{address} · {floor} 层"
    return {
        "version": 1,
        "case_title": world.get("scenario_contract", {}).get("title", "社区消防训练"),
        "objective": "组织居民撤离并逐人清点，完成重点人员护送，核验燃气与房门处置。" if kitchen
                     else "组织居民撤离并逐人清点，完成重点人员护送，核验断电与广播处置。",
        "mode": world.get("parameters", {}).get("training_mode", "assessment"),
        "fire_location": address,
        "population": len(people),
        "priority_people": [{"id": p["id"], "label": p["label"], "floor": p.get("floor")}
                            for p in people if p.get("vulnerable")],
        "responsibilities": [{"id": t["id"], "title": t["title"], "role": t.get("responsible_role", "处置人员")}
                             for t in world.get("tasks", [])],
        "completion_conditions": ["居民实际到达集合点", "到场居民逐人清点", "重点人员完成护送", "处置任务提交有效证据", "运行中指令完成或明确取消"],
        "measures": ["到达与清点人数", "重点人员护送结果", "累计烟气暴露", "处置与核验时刻"],
    }


def project_journey(*, world: dict | None, status: str, elapsed: int,
                    simulation: dict, tasks: list[dict], robot: dict | None,
                    commands: list[dict], events: list) -> dict | None:
    if not world:
        return None
    briefing = deepcopy(world.get("training_briefing") or build_briefing(world))
    people = simulation.get("residents", [])
    remaining = [p for p in people if p.get("status") != "evacuated"]
    remaining_ids = {p["id"] for p in remaining}
    arrivals = [p for p in people if p.get("status") == "evacuated" and not p.get("counted")]
    unassisted = [p for p in people if p.get("vulnerable") and not p.get("assisted")]
    pending = [t for t in tasks if t.get("status") != "completed"]
    active_commands = [c for c in commands if c.get("status") in {"submitted", "accepted", "executing", "queued", "blocked", "paused"}]
    event_types = {e.event_type for e in events}
    alarm = "robot.alarm_confirmed" in event_types
    acknowledged = "participant.acknowledge" in event_types
    missing = [p for p in remaining if p.get("status") == "missing"]
    blocked = [p for p in remaining if p.get("route_reachable") is False]
    # A dispatched escort has not yet met the resident; don't ask for a duplicate.
    assigned = {h.get("resident_id") for h in simulation.get("helpers", [])
                if h.get("state") not in {"completed", "cancelled"}}
    need_help = [p for p in unassisted if p["id"] in remaining_ids and p["id"] not in assigned]
    not_ordered = [p for p in remaining if p.get("release_at", 10**9) >= 10**9 and p.get("indoor_stage") == "room"]
    resident_orders = {rid for e in events if e.event_type == "resident.command"
                       for rid in e.payload.get("resident_ids", [])}
    not_ordered = [p for p in not_ordered if p["id"] not in resident_orders]
    blockers = []
    if remaining:
        blockers.append(f"{len(remaining)} 人尚未到集合点")
    if arrivals:
        blockers.append(f"{len(arrivals)} 名到场居民待清点")
    if unassisted:
        blockers.append(f"{len(unassisted)} 名重点人员尚无护送完成结果")
    if pending:
        blockers.append(f"{len(pending)} 项处置任务待核验")
    if active_commands:
        blockers.append(f"{len(active_commands)} 条指令尚未结束")
    if not alarm:
        blockers.append("尚无火情确认记录")
    if not acknowledged:
        blockers.append("尚无响应确认记录")

    actions = []

    def offer(key, label, detail, kind, target_id=None, severity="normal"):
        actions.append(dict(id=key, label=label, detail=detail, kind=kind,
                            target_id=target_id, severity=severity))

    if status == "ready":
        phase, title = "prepare", "核对简报，开始本次训练"
        offer("start", "开始训练", "启动统一时钟；火情确认后触发责任任务。", "start")
    elif status == "ended":
        phase, title = "review", "核对结果，比较另一种选择"
        offer("review", "查看结果与遗漏", "按事件查看处置、人员结果和评分依据。", "review")
    else:
        phase = "detect" if not alarm else "respond" if remaining else "verify"
        title = {"detect": "确认火情与响应", "respond": "组织撤离，处理受阻事项", "verify": "清点到场居民，补齐处置证据"}[phase]
        if missing or blocked:
            person = (missing or blocked)[0]
            offer("locate", f"定位{person['label']}", "人员失联或当前路线不可达，请核对位置与通道。", "locate", person["id"], "urgent")
        ready_tasks = [t for t in pending if t.get("can_submit")]
        for task in sorted(ready_tasks, key=lambda t: (not t.get("overdue", False), t.get("remaining_seconds", 0)))[:1]:
            offer("verify-" + task["id"], "提交核验：" + task["title"],
                  "已满足提交条件；请核对处置事实并填写证据。", "task", task["id"], "urgent")
        if alarm and not acknowledged:
            offer("acknowledge", "确认报警并组织响应", "记录总控已收到火情并启动响应，不代替现场处置。", "acknowledge", severity="urgent")
        if arrivals:
            offer("rollcall", f"清点 {len(arrivals)} 名到场居民", "只核对实际到场人员，未到场人员仍保留待寻找状态。", "rollcall")
        if alarm and (need_help or not_ordered):
            offer("plan", "安排分流与重点护送", f"{len(not_ordered)} 人待安排撤离，{len(need_help)} 名重点人员待接应；先比较方案，再批准执行。", "plan")
        actionable = [t for t in pending if t.get("status") in {"pending", "executing", "verifying"} and not t.get("can_submit")]
        if actionable:
            task = min(actionable, key=lambda t: (not t.get("overdue", False), t.get("remaining_seconds", 0)))
            offer("task-" + task["id"], task["title"],
                  "；".join(task.get("blockers", [])) or "接收任务、回执到位，再提交处置证据。", "task", task["id"])
        if not alarm:
            offer("detect", "查看火情确认过程", "室内烟感或机器人巡检达到确认条件后，责任任务才会触发。", "indoor" if simulation.get("environment", {}).get("indoor") else "missions")
        if not actions:
            if blockers:
                offer("observe", "查看执行进度", "；".join(blockers), "missions")
            else:
                title = "人员与任务核对完成，可以结束训练"
                offer("finish", "结束训练并查看结果", "冻结本场结果，保留事件、证据与后续分支比较。", "finish")

    waiting = []
    for task in (robot or {}).get("task_queue", []):
        if task.get("status") in {"executing", "queued", "blocked"}:
            seconds = max(0, round(task.get("ends_at_seconds", elapsed) - elapsed))
            waiting.append({"id": task["id"], "label": task.get("label", "机器人任务"),
                            "detail": "路径受阻，需重新指派" if task["status"] == "blocked" else f"约 {seconds} 秒后到达" if task["status"] == "executing" else "等待前序任务",
                            "kind": "missions", "target_id": None, "severity": "normal"})
    return {
        "version": 1, "as_of_seconds": elapsed, "phase": phase, "title": title,
        "paused": status == "paused", "briefing": briefing,
        "briefing_origin": "frozen" if "training_briefing" in world else "legacy_derived",
        "summary": f"{len(people) - len(remaining)}/{len(people)} 人到场，{sum(bool(p.get('counted')) for p in people)} 人已清点；{len(pending)} 项任务待核验。",
        "actions": actions[:3], "additional_action_count": max(0, len(actions) - 3),
        "waiting": [] if status == "ended" else waiting[:2],
        "completion": {"ready": not blockers and status in {"running", "paused"}, "blockers": blockers},
        "resources": {
            "staff_available": sum(p.get("state") == "available" for p in simulation.get("environment", {}).get("response_staff", [])),
            "staff_total": len(world.get("response_staff", [])),
            "robot_state": (robot or {}).get("state"),
            "vehicles": [{"id": v["id"], "name": v.get("name", v["id"]), "state": v.get("state", v.get("status", "unknown"))} for v in simulation.get("vehicles", [])],
        },
    }
