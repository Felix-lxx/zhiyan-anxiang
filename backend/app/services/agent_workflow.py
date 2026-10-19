"""Persistent evacuation workflow built on existing previews, commands and receipts.

Plans are proposals until approved. Domain events, not model prose, settle steps.
The scheduler can resume submitted steps using their durable command IDs.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import math
import re
import hashlib

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from app.models.agent import AgentRun, AgentRunEvent
from app.models.operations import DrillCommand, DrillEvent, DrillSession
from app.schemas.operations import LiveCommand, ResidentCommand
from app.services.agent_resources import robot_support, robot_precondition
from app.services.response_staff import capacity as staff_capacity
from app.services.agent_execution import execution_view

ACTIVE = {"awaiting_approval", "executing", "waiting", "needs_review"}
OPERATING = {"executing", "waiting"}


def ops():
    from app.api.routes import operations
    return operations


def events_for(session, drill):
    return list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))


def note(session, run, kind, message, elapsed):
    run.updated_at = datetime.now(UTC)
    session.add(AgentRunEvent(run_id=run.id, kind=kind, message=message, elapsed_seconds=elapsed))


def buildings_for(data):
    return [{"id": b["id"], "name": b["name"]} for b in data["simulation"].get("world", {}).get("objects", []) if b["type"] == "building"]


def resolve_scope(data, request, interpretation):
    if data.get("engine_version", 1) < 3: raise HTTPException(409, "请新建连续空间演练后使用目标计划。")
    people = data["simulation"]["residents"]
    by_id = {p["id"]: p for p in people}
    if request.resident_ids and not set(request.resident_ids).issubset(by_id): raise HTTPException(422, "所选居民不属于本场次。")
    building = request.building_id or interpretation.get("building_id")
    if not building and not request.resident_ids and re.search(r"[\d一二三四五六七八九十]+\s*号?楼", request.goal):
        raise HTTPException(422, "未能唯一定位目标楼栋，请在目标范围中明确选择建筑，避免误指派全部居民。")
    if building and building not in {b["id"] for b in buildings_for(data)}: raise HTTPException(422, "请选择本场建筑。")
    selected = [p for p in people if (not request.resident_ids or p["id"] in request.resident_ids) and (not building or p.get("building_id") == building)]
    selected = [p for p in selected if p["status"] != "evacuated"]
    if not selected: raise HTTPException(409, "该范围内没有待撤离居民，请核对建筑或到集合点执行清点。")
    resident_buildings = {p.get("building_id") for p in selected}
    if request.robot_broadcast and len(resident_buildings) != 1:
        raise HTTPException(422, "机器人楼门广播需要明确一栋目标建筑，请先选择楼栋或同楼居民。")
    return {"resident_ids": [p["id"] for p in selected], "building_id": building,
            "building_name": next((b["name"] for b in buildings_for(data) if b["id"] == building), "当前选定居民" if request.resident_ids else "全部待撤离居民"),
            "priority_assist": request.priority_assist and interpretation["priority_assist"], "exit_preference": interpretation["exit_preference"],
            "robot_broadcast": request.robot_broadcast,
            "robot_building_id": next(iter(resident_buildings)) if request.robot_broadcast else None,
            "scene_version_id": data["simulation"]["world"]["scene_version_id"],
            "completion": "目标居民到达集合点；重点人员按计划会合护送；" + ("机器人真实到位并广播；" if request.robot_broadcast else "") + "清点由参演人员核验。"}


def build_candidates(session, drill, data, scope):
    operations = ops()
    capacity = staff_capacity(data["simulation"].get("world") or {})
    ids = scope["resident_ids"]
    at = data["elapsed_seconds"]
    events = events_for(session, drill)
    routes = {}
    for exit in ("north", "south"):
        preview = operations.spatial_preview(session, drill, ResidentCommand(resident_ids=ids, exit=exit), events) if ids else {"residents": []}
        routes[exit] = {p["id"]: p for p in preview["residents"] if p["id"] in ids}
    population = {p["id"]: p for p in data["simulation"]["residents"]}
    assist_required = sum(bool(scope["priority_assist"] and population[pid]["vulnerable"]) for pid in ids)
    busy_staff = sum(h["state"] != "completed" for h in data["simulation"].get("helpers", []))
    geometry_issues = [{"edge_id": edge["id"], "name": edge["name"], "reason": edge["blocked_reason"]}
                       for edge in data["simulation"].get("spatial_network", {}).get("edges", []) if edge.get("geometry_blocked")]
    support, resource_steps = robot_support(operations, session, drill, data, scope)
    def route_cost(person):
        if not person.get("route_reachable"): return math.inf
        return person.get("remaining_seconds") or sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in zip(person.get("route_points", []), person.get("route_points", [])[1:]))
    primary = {}
    preference = scope["exit_preference"]
    for index, pid in enumerate(ids):
        costs = {exit: route_cost(routes[exit][pid]) for exit in routes}
        primary[pid] = preference if preference in routes else min(costs, key=lambda exit: (costs[exit], exit != ("north" if index % 2 == 0 else "south")))
    alternatives = [primary, {pid: "south" if exit == "north" else "north" for pid, exit in primary.items()}]
    results = []
    baseline = operations.simulation_state(drill, events, at + 30, session=session)
    baseline_score = operations.calculate_score_data(session, drill, events, baseline)["total_score"]
    for index, assignments in enumerate(alternatives):
        groups, unresolved = [], []
        for exit in ("north", "south"):
            for assist in (False, True):
                members = [pid for pid in ids if assignments[pid] == exit and bool(scope["priority_assist"] and population[pid]["vulnerable"]) == assist]
                unresolved += [pid for pid in members if not routes[exit][pid].get("route_reachable")]
                for start in range(0, len(members), max(1, capacity) if assist else 1000):
                    batch = members[start:start + (max(1, capacity) if assist else 1000)]
                    groups.append({"id": str(uuid4()), "label": f"{'重点护送' if assist else '居民分流'} · {'北门' if exit == 'north' else '南门'} · {len(batch)} 人",
                                   "resident_ids": batch, "exit": exit, "action": "priority_assist" if assist else "evacuate",
                                   "route_edge_ids": sorted({edge for pid in batch for edge in routes[exit][pid].get("route_edge_ids", [])})})
        # Same environment, official score function, bounded 30-second projection.
        # Only available escort slots are released in the forecast; future waves remain waiting.
        simulated, free = list(events), capacity - sum(h["state"] != "completed" for h in data["simulation"].get("helpers", []))
        sequence = data["latest_event_sequence"]
        for group in groups:
            if group["action"] == "priority_assist":
                if len(group["resident_ids"]) > free: continue
                free -= len(group["resident_ids"])
            sequence += 1
            simulated.append(SimpleNamespace(id="agent-preview-" + group["id"], sequence=sequence, elapsed_seconds=at, event_type="resident.command",
                                             payload={k: group[k] for k in ("resident_ids", "exit", "action")}))
        if support and support["can_apply"] and not support.get("already_completed"):
            sequence += 1
            simulated.append(SimpleNamespace(id="agent-preview-robot", sequence=sequence, elapsed_seconds=at,
                event_type="robot.target_assigned", payload={"target": support["target"], "target_x": support["x"], "target_y": support["y"],
                "route_points": support["route_points"], "route_edge_ids": support["route_edge_ids"], "route": support["route"],
                "planned_duration_seconds": support["duration_seconds"], "battery": support["battery_available"] - support["battery_required"] + 3}))
            if support["duration_seconds"] <= 30:
                sequence += 1
                simulated.append(SimpleNamespace(id="agent-preview-broadcast", sequence=sequence,
                    elapsed_seconds=at + support["duration_seconds"], event_type="robot.broadcast_completed",
                    payload={"x": support["x"], "y": support["y"], "target": support["target"], "battery": support["battery_available"] - support["battery_required"]}))
        forecast = operations.simulation_state(drill, simulated, at + 30, session=session)
        predicted = [p for p in forecast["residents"] if p["id"] in ids]
        score = operations.calculate_score_data(session, drill, simulated, forecast)["total_score"]
        assignment_list = [{"id": pid, "label": population[pid]["label"], "exit": assignments[pid], "vulnerable": population[pid]["vulnerable"],
                            "route_points": routes[assignments[pid]][pid].get("route_points", []), "route_edge_ids": routes[assignments[pid]][pid].get("route_edge_ids", []),
                            "route_reachable": routes[assignments[pid]][pid].get("route_reachable", False)} for pid in ids]
        results.append({"id": "candidate-" + str(index + 1), "title": "当前偏好方案" if preference != "balanced" and index == 0 else "路径优先分流" if index == 0 else "另一出口对照",
                        "groups": groups + [{**deepcopy(step), "battery_required": support["battery_required"]} for step in resource_steps],
                        "robot_support": support, "assignments": assignment_list, "geometry_issues": geometry_issues, "navigation_geometry_version": 1,
                        "can_apply": not unresolved and (not assist_required or capacity > 0) and (not support or support["can_apply"]),
                        "assist_resource": {"capacity": capacity, "busy": busy_staff, "required": assist_required,
                                            "waves": math.ceil(assist_required / capacity) if capacity else None},
                        "reason": "本场没有可用值守员，重点护送无法执行；请取消该方案并核对值守资源或调整目标。" if assist_required and not capacity else "当前存在不可达居民，请调整道路或使用另一方案。" if unresolved else support["notice"] if support and not support["can_apply"] else "确认后按真实容量执行；居民与机器人并行，护送分批等待资源。",
                        "metrics": {"north": sum(exit == "north" for exit in assignments.values()), "south": sum(exit == "south" for exit in assignments.values()),
                                    "unreachable": len(unresolved), "arrived": sum(p["status"] == "evacuated" for p in predicted),
                                    "exposed": sum(p.get("smoke_exposure", 0) > 5 for p in predicted), "queue_seconds": round(sum(p.get("queue_seconds", 0) for p in predicted)),
                                    "score": score, "score_delta": score - baseline_score},
                        "forecast_seconds": 30, "forecast_at": at,
                        "coverage": "30 秒居民与首批可用护送资源预演；" + ("机器人按预计到位时刻计入广播，居民不等待机器人；" if support else "") + "后续批次待资源释放，车辆与人工任务沿用当前安排。"})
    return sorted(results, key=lambda p: (not p["can_apply"], p["metrics"]["exposed"], -p["metrics"]["arrived"], p["metrics"]["queue_seconds"]))


def relevant_changes(session, run, after):
    found = []
    ids = set(run.scope["resident_ids"])
    own = {step["command_id"] for step in run.steps}
    robot_owned = run.scope.get("robot_broadcast") and not run.scope.get("robot_broadcast_evidence") and (
        not run.steps or any(s.get("kind") == "robot.command" and s["status"] != "completed" for s in run.steps))
    used_edges = {edge for step in run.steps for edge in step.get("route_edge_ids", [])}
    if not run.steps:
        used_edges = {edge for candidate in run.candidates for person in candidate["assignments"] for edge in person.get("route_edge_ids", [])}
        used_edges.update(edge for c in run.candidates for edge in (c.get("robot_support") or {}).get("route_edge_ids", []))
    own_events = set()
    for receipt in session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == run.drill_session_id, DrillEvent.event_type == "command.accepted")):
        if receipt.payload.get("command_id") in own: own_events.update(receipt.payload.get("event_ids", []))
    for event in session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == run.drill_session_id, DrillEvent.sequence > after).order_by(DrillEvent.sequence)):
        if event.event_type == "resident.command" and event.id not in own_events and ids.intersection(event.payload.get("resident_ids", [])):
            found.append(("taken_over", "目标居民收到人工或其他计划的新指令，自动执行已让出控制。"))
        elif event.event_type == "command.accepted" and event.payload.get("kind") == "residents.assign":
            if ids.intersection(event.payload.get("arguments", {}).get("resident_ids", [])) and event.payload.get("command_id") not in own:
                found.append(("taken_over", "目标居民收到人工或其他计划的新指令，自动执行已让出控制。"))
        elif robot_owned and event.id not in own_events and event.event_type == "robot.replanned":
            found.append(("needs_review", "机器人的路线已调整，请核对新的到位条件后重新比较。"))
        elif robot_owned and event.id not in own_events and event.event_type in {"robot.target_assigned", "robot.task_cancelled", "robot.broadcast_completed"}:
            found.append(("taken_over", "机器人收到外部调度或任务调整，本计划已让出控制，请核对现场。"))
        elif event.event_type in {"inject.channel_blocked", "road.reopened", "inject.resident_missing"}:
            affected = event.payload.get("resident_id") in ids if event.event_type == "inject.resident_missing" else event.payload.get("blocked_edge_id") in used_edges
            if affected:
                found.append(("needs_review", "路网或目标人员状态变化，请重新比较未完成部分。"))
    return found


def run_payload(session, run, data):
    people = [p for p in data["simulation"]["residents"] if p["id"] in run.scope["resident_ids"]]
    history = list(session.scalars(select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(AgentRunEvent.created_at.desc()).limit(16)))
    status = "paused" if data["status"] == "paused" and run.status in OPERATING else run.status
    execution = execution_view(session, run, data)
    return {"id": run.id, "goal": run.goal, "status": status, "reason": run.reason, "revision": run.revision,
            "approved_revision": run.approved_revision, "selected_candidate": run.selected_candidate, "scope": run.scope,
            "candidates": run.candidates if run.status in {"awaiting_approval", "needs_review"} else [], "steps": execution["steps"],
            "execution": {key: value for key, value in execution.items() if key != "steps"},
            "planner": run.planner, "planner_notice": run.planner_notice,
            "summary": {"total": len(people), "arrived": sum(p["status"] == "evacuated" for p in people),
                        "counted": sum(bool(p.get("counted")) for p in people), "assisted": sum(bool(p.get("assisted")) for p in people),
                        "exposed": sum(p.get("smoke_exposure", 0) > 5 for p in people)},
            "history": [{"id": e.id, "kind": e.kind, "message": e.message, "at_seconds": e.elapsed_seconds} for e in history],
            "at_seconds": data["elapsed_seconds"]}


def approve(session, drill, run, candidate_id, revision, identity):
    operations = ops()
    if run.status in {*OPERATING, "completed", "awaiting_rollcall", "unfinished"} and run.approved_revision == revision and run.selected_candidate == candidate_id: return
    if run.status != "awaiting_approval" or run.revision != revision: raise HTTPException(409, "计划已变化，请重新读取方案。")
    if drill.status != "running": raise HTTPException(409, "请先开始或继续演练，再确认执行。")
    candidate = next((p for p in run.candidates if p["id"] == candidate_id), None)
    if not candidate or not candidate["can_apply"]: raise HTTPException(409, "该方案当前不可执行。")
    if any(g.get("action") == "priority_assist" for g in candidate["groups"]):
        fresh = operations.snapshot(session, drill)
        if not staff_capacity(fresh["simulation"].get("world") or {}):
            raise HTTPException(409, "本场没有可用值守员，不能批准重点护送。")
    if run.scope.get("robot_broadcast"):
        fresh = operations.snapshot(session, drill)
        support, _ = robot_support(operations, session, drill, fresh, run.scope)
        if not support["can_apply"]: raise HTTPException(409, support["notice"])
    at = operations.effective_elapsed(drill)
    if candidate.get("navigation_geometry_version") != 1 or at - candidate["forecast_at"] > 45 or relevant_changes(session, run, run.observed_sequence):
        run.status, run.reason = "needs_review", "现场或方案时效已变化，尚未执行。请重新预演。"
        note(session, run, "invalidated", run.reason, at); session.commit()
        raise HTTPException(409, run.reason)
    run.steps = [{**deepcopy(group), "command_id": "agent-" + group["id"], "status": "pending", "reason": "等待当前条件校验", "progress": 0, "last_progress_at": at} for group in candidate["groups"]]
    run.status, run.reason = "executing", "计划已确认，按现有命令接口逐步执行。"
    run.selected_candidate, run.approved_revision = candidate_id, revision
    note(session, run, "approved", "已批准方案：" + candidate["title"], at)
    session.commit()  # Stable action IDs exist before any domain side effect.


def advance_run(session, run, identity):
    if run.status not in OPERATING: return
    owner, now = str(uuid4()), datetime.now(UTC)
    acquired = session.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status.in_(OPERATING),
        or_(AgentRun.lease_owner.is_(None), AgentRun.lease_expires_at <= now)).values(
            lease_owner=owner, lease_expires_at=now + timedelta(seconds=30), execution_epoch=AgentRun.execution_epoch + 1))
    session.commit()
    if not acquired.rowcount: return
    session.refresh(run)
    epoch, revision = run.execution_epoch, run.revision
    def controlled():
        session.execute(select(AgentRun.id).where(AgentRun.id == run.id).with_for_update())
        session.refresh(run)
        if run.lease_owner != owner or run.execution_epoch != epoch or run.revision != revision or run.status not in OPERATING:
            session.rollback(); return False
        run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
        session.flush()
        return True
    try:
        _advance_run(session, run, identity, controlled)
    finally:
        session.rollback()
        session.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.lease_owner == owner,
            AgentRun.execution_epoch == epoch).values(lease_owner=None, lease_expires_at=None))
        session.commit(); session.refresh(run)


def _advance_run(session, run, identity, controlled):
    operations = ops()
    if run.status not in OPERATING: return
    drill = operations.require_drill(session, run.drill_session_id, identity.username)
    data = operations.snapshot(session, drill)
    at = data["elapsed_seconds"]
    if drill.status == "paused": return
    if drill.status == "ended":
        run.status, run.reason = "unfinished", "本场已结束，未完成步骤已冻结。"
        note(session, run, "ended", run.reason, at); session.commit(); return
    if drill.status != "running": return
    changes = relevant_changes(session, run, run.observed_sequence)
    if changes:
        status, reason = next((c for c in changes if c[0] == "taken_over"), changes[0])
        run.status, run.reason = status, reason
        note(session, run, status, reason, at); session.commit(); return
    steps = deepcopy(run.steps)
    people = {p["id"]: p for p in data["simulation"]["residents"]}
    receipts = {c["id"]: c for c in data.get("commands", [])}
    active = {h["resident_id"] for h in data["simulation"].get("helpers", []) if h["state"] != "completed"}
    capacity = staff_capacity(data["simulation"].get("world") or {})
    outcome = None
    for step in steps:
        receipt = receipts.get(step["command_id"])
        if not receipt:
            record = session.scalar(select(DrillCommand).where(DrillCommand.drill_session_id == drill.id, DrillCommand.command_id == step["command_id"]))
            if record:
                receipt = {"status": record.status, "reason": record.reason, "progress": record.progress}
        if receipt:
            step.update(status=receipt["status"], progress=receipt["progress"], reason=receipt["reason"])
        if step["status"] in {"superseded", "cancelled", "failed", "unfinished"}:
            outcome = ("taken_over", "步骤已被替代或结束，自动执行已停止。")
            break
        if step.get("kind") == "robot.command":
            if step["status"] == "blocked":
                outcome = ("needs_review", step["reason"]); break
            if receipt:
                continue
            dependencies = [s for s in steps if s["id"] in step.get("depends_on", [])]
            if any(s["status"] != "completed" for s in dependencies):
                step.update(status="waiting", progress=0, reason="等待本计划机器人真实到位，居民疏散同步进行。")
                continue
            problem = robot_precondition(step, data)
            if problem:
                step.update(status="blocked", reason=problem)
                outcome = ("needs_review", problem); break
            live = LiveCommand(command_id=step["command_id"], kind="robot.command", arguments=step["arguments"], expected_sequence=data["latest_event_sequence"])
            if not controlled(): return
            try:
                data = operations.execute_live_command(drill.id, live, identity, session)
            except HTTPException as error:
                step.update(status="blocked", reason=str(error.detail))
                outcome = ("needs_review", "机器人实时校验未通过：" + str(error.detail)); break
            receipt = next((c for c in data["commands"] if c["id"] == step["command_id"]), None)
            step.update(status=receipt["status"] if receipt else "accepted", progress=receipt["progress"] if receipt else 0,
                        reason=receipt["reason"] if receipt else "已受理，等待真实回执。")
            people = {p["id"]: p for p in data["simulation"]["residents"]}
            continue
        selected = [people[pid] for pid in step["resident_ids"]]
        completed = all(p["status"] == "evacuated" for p in selected)
        escorted = step["action"] != "priority_assist" or all(p.get("assisted") for p in selected)
        if completed and escorted:
            step.update(status="completed", progress=1, reason="已到集合点" + ("，护送会合已完成" if step["action"] == "priority_assist" else "")); continue
        if completed and not escorted:
            outcome = ("needs_review", "人员已到场但未完成计划要求的护送，请人工核对目标。"); break
        if step["status"] == "blocked":
            outcome = ("needs_review", step["reason"]); break
        if receipt: continue
        needed = {p["id"] for p in selected if p["status"] != "evacuated" and p["id"] not in active}
        if step["action"] == "priority_assist" and needed and not capacity:
            step.update(status="blocked", reason="本场没有可用值守资源，无法执行护送。")
            outcome = ("needs_review", step["reason"]); break
        if step["action"] == "priority_assist" and len(active) + len(needed) > capacity:
            step.update(status="waiting", reason=f"等待值守员释放：当前 {len(active)}/{capacity} 名在途。")
            continue
        live = LiveCommand(command_id=step["command_id"], kind="residents.assign", expected_sequence=data["latest_event_sequence"],
                           arguments={k: step[k] for k in ("resident_ids", "exit", "action")})
        if not controlled(): return
        try:
            data = operations.execute_live_command(drill.id, live, identity, session)
        except HTTPException as error:
            session.refresh(run)
            step.update(status="blocked", reason=str(error.detail))
            outcome = ("needs_review", "实时校验未通过：" + str(error.detail))
            break
        receipt = next((c for c in data["commands"] if c["id"] == step["command_id"]), None)
        step.update(status=receipt["status"] if receipt else "accepted", reason=receipt["reason"] if receipt else "已受理", progress=receipt["progress"] if receipt else 0)
        active = {h["resident_id"] for h in data["simulation"].get("helpers", []) if h["state"] != "completed"}
        people = {p["id"]: p for p in data["simulation"]["residents"]}
    if not controlled(): return
    previous = {s["id"]: s["status"] for s in run.steps}
    helpers = {h["resident_id"]: h for h in data["simulation"].get("helpers", [])}
    for step in steps:
        # Record actual movement, not elapsed time, as progress. A warning never
        # cancels an accepted command or silently replaces an approved route.
        observed = [(pid, round(people[pid]["x"], 1), round(people[pid]["y"], 1),
                     round(people[pid].get("height", 0), 1), people[pid]["status"])
                    for pid in step.get("resident_ids", []) if pid in people]
        escort_observed = [(pid, round(helpers[pid]["x"], 1), round(helpers[pid]["y"], 1),
                            round(helpers[pid].get("height", 0), 1), helpers[pid]["state"])
                           for pid in step.get("resident_ids", []) if pid in helpers]
        signature = hashlib.sha256(repr((step["status"], round(step["progress"], 3), observed, escort_observed)).encode()).hexdigest()
        if signature != step.get("progress_signature"):
            step.update(progress_signature=signature, last_progress_at=at)
        if previous.get(step["id"]) != step["status"]:
            note(session, run, "step." + step["status"], step["label"] + "：" + step["reason"], at)
    run.steps = steps
    if outcome:
        run.status, run.reason = outcome
        note(session, run, run.status, run.reason, at)
    run.observed_sequence = data["latest_event_sequence"]
    if run.status in OPERATING:
        all_arrived = all(people[pid]["status"] == "evacuated" for pid in run.scope["resident_ids"])
        if all_arrived and all(s["status"] == "completed" for s in steps):
            counted = all(people[pid].get("counted") for pid in run.scope["resident_ids"])
            run.status = "completed" if counted else "awaiting_rollcall"
            run.reason = "目标居民疏散、护送与集合核验完成。" if counted else "目标居民已到集合点；等待参演人员核验，助手不会代签清点。"
            note(session, run, run.status, run.reason, at)
        else:
            run.status = "waiting" if any(s["status"] == "waiting" for s in steps) else "executing"
            run.reason = next((s["reason"] for s in steps if s["status"] in {"waiting", "blocked"}), "已提交步骤持续执行，人员沿真实通道移动。")
    run.updated_at = datetime.now(UTC)
    session.commit()


def reconcile_rollcall(session, run, identity):
    if run.status != "awaiting_rollcall": return
    data = ops().snapshot(session, ops().require_drill(session, run.drill_session_id, identity.username))
    selected = [p for p in data["simulation"]["residents"] if p["id"] in run.scope["resident_ids"]]
    if all(p.get("counted") for p in selected):
        run.status, run.reason = "completed", "目标居民疏散、护送与集合核验完成。"
        note(session, run, "completed", run.reason, data["elapsed_seconds"]); session.commit()
    elif data["status"] == "ended":
        run.status, run.reason = "unfinished", "本场已结束，目标居民仍有未核验清点记录；已到场不等于目标完成。"
        note(session, run, "unfinished", run.reason, data["elapsed_seconds"]); session.commit()


async def serve():
    import asyncio
    import logging
    from app.core.database import SessionLocal
    @ops().serialized_command
    def tick_one(run_id):
        with SessionLocal() as session:
            run = session.get(AgentRun, run_id)
            if not run: return
            # Domain command execution rechecks ownership; no user access token is stored.
            identity = SimpleNamespace(username=run.actor)
            advance_run(session, run, identity)
            reconcile_rollcall(session, run, identity)
    while True:
        try:
            with SessionLocal() as session:
                ids = list(session.scalars(select(AgentRun.id).where(AgentRun.status.in_([*OPERATING, "awaiting_rollcall"]))))
            for run_id in ids:
                try: await asyncio.to_thread(tick_one, run_id)
                except Exception: logging.getLogger(__name__).exception("目标计划 %s 推进失败，将从命令台账恢复", run_id)
        except Exception: logging.getLogger(__name__).exception("目标计划调度失败")
        await asyncio.sleep(2)
