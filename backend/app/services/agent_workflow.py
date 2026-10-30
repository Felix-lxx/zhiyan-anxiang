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
from app.models.agent import AgentRun, AgentRunEvent, AgentDecisionCheck
from app.models.operations import DrillCommand, DrillEvent, DrillSession
from app.schemas.operations import LiveCommand, ResidentCommand
from app.services.agent_resources import robot_support, robot_precondition, owned_steps
from app.services.response_staff import capacity as staff_capacity
from app.services.agent_execution import execution_view
from app.services.agent_allocation import allocate_exits
from app.services.agent_outcomes import register_check, settle_checks, outcome_payload
from app.application.drill_commands import CommandOrigin, CommandRejected
from app.bootstrap.commands import command_application
from app.services import agent_claims
from app.services.agent_task_graph import compile_graph, distinct_candidates, graph_view, validate_graph

ACTIVE = {"awaiting_approval", "executing", "waiting", "needs_review"}
OPERATING = {"executing", "waiting"}


def ops():
    from app.api.routes import operations
    return operations


def forecast_horizon(routes, support=None):
    """Return one bounded comparison horizon for every candidate in a run."""
    estimates = [
        float(route.get("remaining_seconds", route.get("estimated_seconds")) or 0)
        for options in routes.values()
        for route in options.values()
        if route.get("route_reachable")
    ]
    if support and support.get("can_apply"):
        estimates.append(float(support.get("duration_seconds") or 0))
    return max(30, min(90, int(math.ceil(max(estimates, default=30) / 10) * 10)))


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
    resident_buildings = sorted({p.get("building_id") for p in selected if p.get("building_id")})
    return {"resident_ids": [p["id"] for p in selected], "building_id": building,
            "building_name": next((b["name"] for b in buildings_for(data) if b["id"] == building), "当前选定居民" if request.resident_ids else "全部待撤离居民"),
            "priority_assist": request.priority_assist and interpretation["priority_assist"], "exit_preference": interpretation["exit_preference"],
            "robot_broadcast": request.robot_broadcast,
            # Keep the singular field for historical runs while new runs retain
            # every affected building. The robot compiler turns this into a
            # sequential move/broadcast chain instead of rejecting a community-
            # wide evacuation goal.
            "robot_building_id": resident_buildings[0] if request.robot_broadcast and resident_buildings else None,
            "robot_building_ids": resident_buildings if request.robot_broadcast else [],
            "scene_version_id": data["simulation"]["world"]["scene_version_id"],
            "completion": "目标居民到达集合点；重点人员按计划会合护送；" + ("机器人真实到位并广播；" if request.robot_broadcast else "") + "清点由参演人员核验。"}


def build_candidates(session, drill, data, scope, run=None):
    operations = ops()
    capacity = staff_capacity(data["simulation"].get("world") or {})
    ids = scope["resident_ids"]
    id_set = set(ids)
    at = data["elapsed_seconds"]
    events = events_for(session, drill)
    routes = {}
    for exit in ("north", "south"):
        preview = operations.spatial_preview(session, drill, ResidentCommand(resident_ids=ids, exit=exit), events) if ids else {"residents": []}
        routes[exit] = {p["id"]: p for p in preview["residents"] if p["id"] in id_set}
    population = {p["id"]: p for p in data["simulation"]["residents"]}
    assist_required = sum(bool(scope["priority_assist"] and population[pid]["vulnerable"]) for pid in ids)
    busy_staff = sum(h["state"] != "completed" for h in data["simulation"].get("helpers", []))
    geometry_issues = [{"edge_id": edge["id"], "name": edge["name"], "reason": edge["blocked_reason"]}
                       for edge in data["simulation"].get("spatial_network", {}).get("edges", []) if edge.get("geometry_blocked")]
    support, resource_steps = robot_support(operations, session, drill, data, scope, run)
    preference = scope["exit_preference"]
    alternatives = allocate_exits(routes, population, data["simulation"].get("spatial_network", {}).get("edges", []), ids, preference)
    from app.services.agent_containment import source_door, occupied
    door = source_door(data)
    if door and door['state'] != 'closed':
        # Compare a different environmental action, even when both exit policies
        # resolve to the same route. Occupancy is checked again during execution.
        alternatives.append((deepcopy(alternatives[1][0]), {**deepcopy(alternatives[1][1]),
            'rule': 'containment', 'description': '居民先撤离起火房间，安全条件满足后关闭房门，限制烟气向走廊交换。',
            'door_id': door['id']}))
    results = []
    forecast_seconds = forecast_horizon(routes, support)
    baseline = operations.simulation_state(drill, events, at + forecast_seconds, session=session)
    baseline_score = operations.calculate_score_data(session, drill, events, baseline)["total_score"]
    baseline_people = [p for p in baseline["residents"] if p["id"] in id_set]
    baseline_metrics = {"arrived": sum(p["status"] == "evacuated" for p in baseline_people),
        "exposed": sum(p.get("smoke_exposure", 0) > 5 for p in baseline_people),
        "queue_seconds": round(sum(p.get("queue_seconds", 0) for p in baseline_people))}
    for index, (assignments, allocation) in enumerate(alternatives):
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
        # Same environment and official score function.  The shared bounded
        # horizon covers the slowest selected route, so every candidate is
        # compared at the same meaningful point instead of a fixed 30 seconds.
        # Only available escort slots are released in the forecast; future waves remain waiting.
        escorted = {h["resident_id"] for h in data["simulation"].get("helpers", []) if h["state"] != "completed"}
        simulated, free = list(events), max(0, capacity - len(escorted))
        sequence = data["latest_event_sequence"]
        for group in groups:
            if group["action"] == "priority_assist":
                needed = set(group["resident_ids"]) - escorted
                if len(needed) > free: continue
                free -= len(needed)
                escorted.update(needed)
            sequence += 1
            simulated.append(SimpleNamespace(id="agent-preview-" + group["id"], sequence=sequence, elapsed_seconds=at, event_type="resident.command",
                                             payload={k: group[k] for k in ("resident_ids", "exit", "action")}))
        if support and support["can_apply"] and not support.get("already_completed"):
            if not support.get("reusing_task"):
                sequence += 1
                simulated.append(SimpleNamespace(id="agent-preview-robot", sequence=sequence, elapsed_seconds=at,
                    event_type="robot.target_assigned", payload={"target": support["target"], "target_x": support["x"], "target_y": support["y"],
                    "route_points": support["route_points"], "route_edge_ids": support["route_edge_ids"], "route": support["route"],
                    "planned_duration_seconds": support["duration_seconds"], "battery": support["battery_available"] - support["battery_required"] + 3}))
            if support.get("target_count", 1) == 1 and support["duration_seconds"] <= forecast_seconds:
                sequence += 1
                simulated.append(SimpleNamespace(id="agent-preview-broadcast", sequence=sequence,
                    elapsed_seconds=at + support["duration_seconds"], event_type="robot.broadcast_completed",
                    payload={"x": support["x"], "y": support["y"], "target": support["target"], "battery": support["battery_available"] - support["battery_required"]}))
        containment = []
        if allocation.get('rule') == 'containment':
            containment = [{'id': str(uuid4()), 'label': '起火房间撤空后关闭房门',
                'kind': 'indoor.door.set', 'arguments': {'door_id': door['id'], 'state': 'closed'},
                'resident_ids': [], 'depends_on': [], 'route_edge_ids': []}]
            interim = operations.simulation_state(drill, simulated, at + 15, session=session)
            if not occupied({'simulation': interim}, door):
                sequence += 1
                simulated.append(SimpleNamespace(id='agent-preview-containment', sequence=sequence, elapsed_seconds=at+15,
                    event_type='indoor.door_changed', payload={'door_id': door['id'], 'room_id': door['room_id'], 'state': 'closed'}))
        forecast = operations.simulation_state(drill, simulated, at + forecast_seconds, session=session)
        predicted = [p for p in forecast["residents"] if p["id"] in id_set]
        score = operations.calculate_score_data(session, drill, simulated, forecast)["total_score"]
        assignment_list = [{"id": pid, "label": population[pid]["label"], "exit": assignments[pid], "vulnerable": population[pid]["vulnerable"],
                            "route_points": routes[assignments[pid]][pid].get("route_points", []), "route_edge_ids": routes[assignments[pid]][pid].get("route_edge_ids", []),
                            "route_reachable": routes[assignments[pid]][pid].get("route_reachable", False)} for pid in ids]
        title = {'path': '当前偏好方案' if preference != 'balanced' else '路径优先分流',
                 'risk_capacity': '风险与容量分流', 'north_priority': '北侧出口优先',
                 'south_priority': '南侧出口优先', 'containment': '安全撤空与房门控烟'}[allocation['rule']]
        results.append({"id": "candidate-" + str(index + 1), "title": title,
                        "allocation": allocation, "baseline_metrics": baseline_metrics,
                        "groups": groups + containment + [{**deepcopy(step), "battery_required": step.get("battery_required", support["battery_required"])} for step in resource_steps],
                        "robot_support": support, "assignments": assignment_list, "geometry_issues": geometry_issues, "navigation_geometry_version": 1,
                        "can_apply": not unresolved and (not assist_required or capacity > 0) and (not support or support["can_apply"]),
                        "assist_resource": {"capacity": capacity, "busy": busy_staff, "required": assist_required,
                                            "waves": math.ceil(assist_required / capacity) if capacity else None},
                        "reason": "本场没有可用值守员，重点护送无法执行；请取消该方案并核对值守资源或调整目标。" if assist_required and not capacity else "当前存在不可达居民，请调整道路或使用另一方案。" if unresolved else support["notice"] if support and not support["can_apply"] else "确认后按真实容量执行；居民与机器人并行，护送分批等待资源。",
                        "metrics": {"north": sum(exit == "north" for exit in assignments.values()), "south": sum(exit == "south" for exit in assignments.values()),
                                    "unreachable": len(unresolved), "arrived": sum(p["status"] == "evacuated" for p in predicted),
                                    "exposed": sum(p.get("smoke_exposure", 0) > 5 for p in predicted), "queue_seconds": round(sum(p.get("queue_seconds", 0) for p in predicted)),
                                    "score": score, "score_delta": score - baseline_score},
                        "forecast_seconds": forecast_seconds, "forecast_at": at, "forecast_sequence": data["latest_event_sequence"],
                        "coverage": f"{forecast_seconds} 秒居民与首批可用护送资源预演；" + ("机器人按预计到位时刻计入广播，居民不等待机器人；" if support else "") + "后续批次待资源释放，车辆与人工任务沿用当前安排。"})
    # The director workspace deliberately presents at most two actionable
    # decisions.  More alternatives increase review time without improving
    # the plan: keep the best forecast and one materially different fallback;
    # equivalent rules remain visible in ``equivalent_rules``.
    candidates = distinct_candidates(sorted(results, key=lambda p: (not p["can_apply"], p["metrics"]["exposed"], -p["metrics"]["arrived"], p["metrics"]["queue_seconds"])))
    if len(candidates) <= 2:
        return candidates
    # A containment proposal is a different physical action, not a cosmetic
    # label. Keep it alongside the best route candidate so the agent cannot
    # hide the only door-control option while still limiting the UI to two.
    containment = next((item for item in candidates if item.get('allocation', {}).get('rule') == 'containment'), None)
    if containment is not None and candidates[0] is not containment:
        return [candidates[0], containment]
    return candidates[:2]


def relevant_changes(session, run, after):
    found = []
    ids = set(run.scope["resident_ids"])
    own = {step["command_id"] for step in owned_steps(run) if step.get("command_id")}
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
        elif event.event_type == "robot.alarm_confirmed" and run.scope.get("robot_broadcast") and not any(c.get("can_apply") for c in run.candidates):
            found.append(("needs_review", "自动火情巡检已完成，请按当前机器人位置重新比较并确认楼门广播任务。"))
        elif robot_owned and event.id not in own_events and event.event_type == "robot.replanned":
            found.append(("needs_review", "机器人的路线已调整，请核对新的到位条件后重新比较。"))
        elif robot_owned and event.id not in own_events and event.event_type in {"robot.target_assigned", "robot.task_cancelled", "robot.broadcast_completed"}:
            # Automatic fire inspection is a system prerequisite, not a human
            # takeover of the evacuation plan. Its completion invalidates the
            # old preview through robot.alarm_confirmed and asks for replan.
            if event.event_type == "robot.target_assigned" and event.payload.get("purpose") == "inspection":
                continue
            found.append(("taken_over", "机器人收到外部调度或任务调整，本计划已让出控制，请核对现场。"))
        elif event.event_type in {"inject.channel_blocked", "road.reopened", "inject.resident_missing"}:
            affected = event.payload.get("resident_id") in ids if event.event_type == "inject.resident_missing" else event.payload.get("blocked_edge_id") in used_edges
            if affected:
                found.append(("needs_review", "路网或目标人员状态变化，请重新比较未完成部分。"))
        elif event.event_type == 'indoor.door_changed' and event.id not in own_events and not run.steps:
            found.append(('needs_review', '室内房门已变化，通行与烟气条件需要重新比较。'))
    return found


def run_payload(session, run, data):
    ids = set(run.scope["resident_ids"])
    people = [p for p in data["simulation"]["residents"] if p["id"] in ids]
    history = list(session.scalars(select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(AgentRunEvent.created_at.desc()).limit(16)))
    status = "paused" if data["status"] == "paused" and run.status in OPERATING else run.status
    execution = execution_view(session, run, data)
    approval_guard = None
    if run.status == "awaiting_approval":
        age = max(0, data["elapsed_seconds"] - min((c["forecast_at"] for c in run.candidates), default=data["elapsed_seconds"]))
        changes = relevant_changes(session, run, run.observed_sequence)
        expired = age > 45 or any(c.get("navigation_geometry_version") != 1 for c in run.candidates)
        review = bool(changes) or expired
        reason = changes[0][1] if changes else "预演起点已超过45秒，请按当前现场重新比较。" if expired else "确认方案后继续演练并执行。" if data['status'] == 'paused' else "请先开始演练，再确认执行。" if data["status"] != "running" else "现场条件有效，核对方案后可确认执行。"
        approval_guard = {"can_approve": not review and data["status"] in {"running", "paused"}, "needs_replan": review,
                          "age_seconds": age, "reason": reason}
        if review:
            execution["coordination"]["next_action"] = {"kind": "replan", "label": "按当前现场重新比较", "reason": reason}
            lane = next(l for l in execution["coordination"]["lanes"] if l["id"] == "planning")
            lane.update(state="review", detail=reason)
    return {"id": run.id, "goal": run.goal, "status": status, "drill_status": data['status'], "reason": run.reason, "revision": run.revision,
            "task_graph": graph_view(execution['steps'], data, run.scope['resident_ids']),
            "resources": agent_claims.resource_view(session, run),
            "outcomes": outcome_payload(session, run),
            "decision": next((a["decision"] for a in reversed(run.evidence) if a.get("decision")), None),
            "recovery": next((a["recovery"] for a in reversed(run.evidence) if a.get("recovery")), None),
            "approval_guard": approval_guard,
            "updated_at_us": int((run.updated_at if run.updated_at.tzinfo else run.updated_at.replace(tzinfo=UTC)).timestamp() * 1_000_000),
            "created_at_us": int((run.created_at if run.created_at.tzinfo else run.created_at.replace(tzinfo=UTC)).timestamp() * 1_000_000),
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
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    if run.status in {*OPERATING, "completed", "awaiting_rollcall", "unfinished"} and run.approved_revision == revision and run.selected_candidate == candidate_id: return
    if run.status != "awaiting_approval" or run.revision != revision: raise HTTPException(409, "计划已变化，请重新读取方案。")
    if drill.status not in {'running', 'paused'}: raise HTTPException(409, "请先开始演练，再确认执行。")
    candidate = next((p for p in run.candidates if p["id"] == candidate_id), None)
    if not candidate or not candidate["can_apply"]: raise HTTPException(409, "该方案当前不可执行。")
    if any(g.get("action") == "priority_assist" for g in candidate["groups"]):
        fresh = operations.snapshot(session, drill)
        if not staff_capacity(fresh["simulation"].get("world") or {}):
            raise HTTPException(409, "本场没有可用值守员，不能批准重点护送。")
    if run.scope.get("robot_broadcast"):
        fresh = operations.snapshot(session, drill)
        support, _ = robot_support(operations, session, drill, fresh, run.scope, run)
        if not support["can_apply"]: raise HTTPException(409, support["notice"])
    at = operations.effective_elapsed(drill)
    if candidate.get("navigation_geometry_version") != 1 or at - candidate["forecast_at"] > 45 or relevant_changes(session, run, run.observed_sequence):
        run.status, run.reason = "needs_review", "现场或方案时效已变化，尚未执行。请重新预演。"
        note(session, run, "invalidated", run.reason, at); session.commit()
        raise HTTPException(409, run.reason)
    run.steps = compile_graph(candidate['groups'], at)
    run.evidence = [*run.evidence, {"decision": {"revision": revision, "candidate_id": candidate_id,
        "title": candidate["title"], "approved_at": at, "forecast_at": candidate["forecast_at"],
        "forecast_seconds": candidate["forecast_seconds"], "metrics": deepcopy(candidate["metrics"]),
        "allocation": deepcopy(candidate.get("allocation")), "baseline_metrics": deepcopy(candidate.get("baseline_metrics"))}}]
    run.status, run.reason = "executing", "计划已确认，按现有命令接口逐步执行。"
    run.selected_candidate, run.approved_revision = candidate_id, revision
    acquired, resource_reason = agent_claims.acquire(session, run, operations.snapshot(session, drill))
    if not acquired:
        run.status, run.reason = 'waiting', resource_reason
    note(session, run, 'resources.owned' if acquired else 'resources.waiting', resource_reason, at)
    register_check(session, run, candidate, at)
    note(session, run, "approved", "已批准方案：" + candidate["title"], at)
    if drill.status == 'paused':
        drill.status, drill.started_at = 'running', datetime.now(UTC)
        operations.append_event(session, drill, 'drill.resumed', identity.username,
            '方案已批准，现场继续并开始执行。', {'reason': 'agent_approved', 'run_id': run.id})
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
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    data = operations.snapshot(session, drill)
    at = data["elapsed_seconds"]
    if drill.status == "paused": return
    if drill.status == "ended":
        finalize_run(session, run, data)
        session.commit(); return
    if drill.status != "running": return
    changes = relevant_changes(session, run, run.observed_sequence)
    if changes:
        status, reason = next((c for c in changes if c[0] == "taken_over"), changes[0])
        run.status, run.reason = status, reason
        if status == 'taken_over': agent_claims.release(session, run.id)
        note(session, run, status, reason, at); session.commit(); return
    try:
        validate_graph(run.steps)
    except ValueError as error:
        run.status, run.reason = 'needs_review', str(error) + ' 自动下令已暂停，请重新比较。'
        note(session, run, 'graph.invalid', run.reason, at)
        session.commit(); return
    acquired, resource_reason = agent_claims.acquire(session, run, data)
    if not acquired:
        changed = run.reason != resource_reason
        run.status, run.reason = 'waiting', resource_reason
        if changed: note(session, run, 'resources.waiting', resource_reason, at)
        session.commit(); return
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
        dependencies = [s for s in steps if s['id'] in step.get('depends_on', [])]
        if not receipt and any(s['status'] != 'completed' for s in dependencies):
            step.update(status='waiting', progress=0, reason='等待前置步骤：' + '、'.join(s['label'] for s in dependencies if s['status'] != 'completed'))
            continue
        if step.get('kind') == 'indoor.door.set':
            if receipt:
                continue
            from app.services.agent_containment import source_door, occupied
            door = source_door(data)
            if not door or door['id'] != step['arguments']['door_id']:
                outcome = ('needs_review', '起火房门已变化，请重新比较。'); break
            if occupied(data, door):
                step.update(status='waiting', reason='等待起火房间及门洞撤空；保留居民和护送员通路。')
                continue
            if door['state'] == 'closed':
                step.update(status='completed', progress=1, reason='现场房门已关闭，已核对状态。'); continue
            if not controlled(): return
            try:
                data = command_application().execute(session, drill.id, LiveCommand(command_id=step['command_id'],
                    kind='indoor.door.set', arguments=step['arguments']), identity,
                    CommandOrigin('agent', run.id, run.approved_revision, step['id']))
                step.update(status='completed', progress=1, reason='已确认无人占用并关闭房门；烟气与通行同步改变。')
            except CommandRejected as error:
                outcome = ('needs_review', str(error.detail)); break
            continue
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
                data = command_application().execute(session, drill.id, live, identity,
                    CommandOrigin('agent', run.id, run.approved_revision, step['id']))
            except CommandRejected as error:
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
            data = command_application().execute(session, drill.id, live, identity,
                CommandOrigin('agent', run.id, run.approved_revision, step['id']))
        except CommandRejected as error:
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
        robot = data.get("robot") or {}
        robot_observed = (robot.get("state"), round(robot.get("x", 0), 1), round(robot.get("y", 0), 1)) if step.get("kind") == "robot.command" else None
        signature = hashlib.sha256(repr((step["status"], round(step["progress"], 3), observed, escort_observed, robot_observed)).encode()).hexdigest()
        if signature != step.get("progress_signature"):
            step.update(progress_signature=signature, last_progress_at=at)
        if previous.get(step["id"]) != step["status"]:
            note(session, run, "step." + step["status"], step["label"] + "：" + step["reason"], at)
    run.steps = steps
    if outcome:
        run.status, run.reason = outcome
        if run.status == 'taken_over': agent_claims.release(session, run.id)
        note(session, run, run.status, run.reason, at)
    run.observed_sequence = data["latest_event_sequence"]
    if run.status in OPERATING:
        all_arrived = all(people[pid]["status"] == "evacuated" for pid in run.scope["resident_ids"])
        assist_missing = run.scope["priority_assist"] and any(people[pid]["status"] == "evacuated" and
            people[pid]["vulnerable"] and not people[pid].get("assisted") for pid in run.scope["resident_ids"])
        if assist_missing:
            run.status, run.reason = "needs_review", "已有重点人员到场但缺少会合护送依据，请核对原计划，不能以重新分组替代护送证据。"
            note(session, run, "needs_review", run.reason, at)
        elif all_arrived and all(s["status"] == "completed" for s in steps):
            counted = all(people[pid].get("counted") for pid in run.scope["resident_ids"])
            tasks_done = not run.scope.get('include_case_tasks') or all(t['status'] == 'completed' for t in data.get('tasks', []))
            run.status = "completed" if counted and tasks_done else "awaiting_rollcall"
            agent_claims.release(session, run.id)
            run.reason = "目标行动、责任任务与集合核验完成。" if counted and tasks_done else "人员行动已完成；请完成案例责任任务和集合清点。"
            note(session, run, run.status, run.reason, at)
        else:
            run.status = "waiting" if any(s["status"] == "waiting" for s in steps) else "executing"
            run.reason = next((s["reason"] for s in steps if s["status"] in {"waiting", "blocked"}), "已提交步骤持续执行，人员沿真实通道移动。")
    run.updated_at = datetime.now(UTC)
    session.commit()


def finalize_run(session, run, data):
    """Freeze one plan from authoritative receipts and the final world.

    Ending a drill can race the two-second agent scheduler. Re-read every
    receipt and resident result before assigning the terminal plan status so a
    completed plan cannot be frozen as unfinished merely because the next
    scheduler tick has not happened yet.
    """
    execution = execution_view(session, run, data)
    refreshed = {step["id"]: step for step in execution["steps"]}
    steps = deepcopy(run.steps)
    for step in steps:
        view = refreshed.get(step["id"])
        if view:
            step.update({key: view[key] for key in ("status", "progress", "reason") if key in view})
    run.steps = steps
    people_by_id = {person["id"]: person for person in data["simulation"]["residents"]}
    people = [people_by_id[pid] for pid in run.scope.get("resident_ids", []) if pid in people_by_id]
    all_steps = bool(steps) and all(step["status"] == "completed" for step in steps)
    all_arrived = bool(people) and all(person["status"] == "evacuated" for person in people)
    all_counted = all_arrived and all(person.get("counted") for person in people)
    assist_ok = not run.scope.get("priority_assist") or all(
        not person.get("vulnerable") or person.get("assisted") for person in people)
    agent_claims.release(session, run.id)
    tasks_ok = not run.scope.get('include_case_tasks') or all(t['status'] == 'completed' for t in data.get('tasks', []))
    if all_steps and all_counted and assist_ok and tasks_ok:
        run.status, run.reason = "completed", "目标居民疏散、护送、机器人协同与集合核验均已完成，结果已冻结。"
        event_kind = "completed"
    else:
        missing = sum(person["status"] != "evacuated" for person in people)
        unchecked = sum(person["status"] == "evacuated" and not person.get("counted") for person in people)
        incomplete_steps = sum(step["status"] != "completed" for step in steps)
        run.status = "unfinished"
        run.reason = f"本场结果已冻结：未完成步骤 {incomplete_steps} 项、未到场 {missing} 人、未清点 {unchecked} 人。"
        event_kind = "unfinished"
    run.observed_sequence = data["latest_event_sequence"]
    note(session, run, event_kind, run.reason, data["elapsed_seconds"])


def finalize_runs_for_end(session, drill, identity):
    """Synchronously settle active plans before the score and snapshot freeze."""
    data = ops().snapshot(session, drill)
    runs = list(session.scalars(select(AgentRun).where(
        AgentRun.drill_session_id == drill.id,
        AgentRun.status.in_([*ACTIVE, *OPERATING, "awaiting_rollcall"]),
    )))
    for run in runs:
        finalize_run(session, run, data)


def reconcile_rollcall(session, run, identity):
    if run.status != "awaiting_rollcall": return
    data = ops().snapshot(session, ops().require_drill(session, run.drill_session_id, identity.username))
    selected = [p for p in data["simulation"]["residents"] if p["id"] in run.scope["resident_ids"]]
    tasks_done = not run.scope.get('include_case_tasks') or all(t['status'] == 'completed' for t in data.get('tasks', []))
    if all(p.get("counted") for p in selected) and tasks_done:
        agent_claims.release(session, run.id)
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
            settle_checks(session, run, ops())
    while True:
        try:
            with SessionLocal() as session:
                pending = select(AgentDecisionCheck.run_id).where(AgentDecisionCheck.status == "pending")
                ids = list(session.scalars(select(AgentRun.id).where(or_(
                    AgentRun.status.in_([*OPERATING, "awaiting_rollcall"]), AgentRun.id.in_(pending)))))
            for run_id in ids:
                try: await asyncio.to_thread(tick_one, run_id)
                except Exception: logging.getLogger(__name__).exception("目标计划 %s 推进失败，将从命令台账恢复", run_id)
        except Exception: logging.getLogger(__name__).exception("目标计划调度失败")
        await asyncio.sleep(2)
