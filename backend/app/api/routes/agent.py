"""Goal proposals and explicit approvals for the existing exercise command engine."""
import hashlib
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.routes import operations
from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.agent import AgentRun
from app.schemas.agent import GoalCreate, PlanAction
from app.services.agent_planner import interpret_goal
from app.services.agent_contract import goal_constraints, tool_report
from app.services.agent_tool_planning import recommend
from app.services.agent_workflow import ACTIVE, OPERATING, advance_run, approve, buildings_for, build_candidates, note, resolve_scope, run_payload

router = APIRouter(tags=["goal workflows"])


def pause_review(session, drill, enabled):
    if enabled and drill.status == 'running':
        drill.elapsed_seconds = operations.effective_elapsed(drill)
        drill.started_at = None
        drill.status = 'paused'
        operations.append_event(session, drill, 'drill.paused', '方案审阅',
            '已暂停现场供方案审阅；确认执行后自动继续。', {'reason': 'agent_review'})
        session.flush()


@operations.serialized_command
def freeze_for_review(session, drill_id, identity, payload):
    """Freeze field time before candidate simulation or model/tool planning."""
    drill = operations.require_drill(session, drill_id, identity.username)
    session.execute(select(type(drill).id).where(type(drill).id == drill_id).with_for_update())
    # Reject impossible explicit object/floor selections before committing a
    # pause for an external model request. Model interpretation cannot make a
    # missing resident or an empty floor valid.
    if payload.resident_ids or payload.building_id or payload.floors:
        data = operations.snapshot(session, drill)
        interpretation, _, _ = interpret_goal(payload.goal, buildings_for(data), False)
        resolve_scope(data, payload, interpretation)
    pause_review(session, drill, payload.pause_for_review)
    session.commit()
    return operations.snapshot(session, drill)


def request_fingerprint(payload):
    return hashlib.sha256(json.dumps(payload.model_dump(exclude={"request_id"}), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_retry(run, payload, username):
    if run.actor != username or run.scope.get("request_fingerprint") != request_fingerprint(payload):
        raise HTTPException(409, "请求编号已用于另一目标或参数，请重新提交。")


def owned_run(session, drill_id, run_id, identity):
    drill = operations.require_drill(session, drill_id, identity.username)
    run = session.get(AgentRun, run_id)
    if not run or run.drill_session_id != drill.id or run.actor != identity.username:
        raise HTTPException(404, "未找到本场目标计划。")
    return drill, run


@router.get("/drills/{drill_id}/agent/runs")
def list_runs(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    data = operations.snapshot(session, drill)
    runs = session.scalars(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.actor == identity.username).order_by(AgentRun.status.in_([*ACTIVE, 'awaiting_rollcall']).desc(), AgentRun.created_at.desc()).limit(8)).all()
    return {"buildings": buildings_for(data), "runs": [run_payload(session, r, data) for r in runs], "drill_status": drill.status}


@router.post("/drills/{drill_id}/agent/runs", status_code=201)
def create_run(drill_id: str, payload: GoalCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    existing = session.scalar(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.request_id == payload.request_id))
    if existing:
        validate_retry(existing, payload, identity.username)
        return run_payload(session, existing, operations.snapshot(session, drill))
    if drill.status not in {"running", "paused", "ready"}: raise HTTPException(409, "本场已结束，请新开一轮再制定计划。")
    from app.services.agent_contract import validate_goal_capabilities
    validate_goal_capabilities(payload.goal)
    if not any(word in payload.goal for word in ("疏散", "撤离", "分流", "护送")):
        raise HTTPException(422, "当前目标计划支持居民疏散、分流和重点护送；其他问题请使用场景对话，车辆仍从车辆调度操作。")
    goal_constraints(payload)
    if not payload.use_model:
        # Local interpretation performs no external I/O. Keep pause, scope
        # validation and proposal creation in the same transaction so a rejected
        # range cannot leave a committed review pause behind.
        pause_review(session, drill, payload.pause_for_review)
        data = operations.snapshot(session, drill)
        interpretation, planner, notice = interpret_goal(payload.goal, buildings_for(data), False)
        return _create_after_interpretation(session, drill_id, payload, interpretation, planner, notice, identity)
    frozen_data = freeze_for_review(session, drill_id, identity, payload) if payload.pause_for_review else None
    data = frozen_data or operations.snapshot(session, drill)
    buildings = buildings_for(data)
    session.rollback()  # No DB locks or open read transaction while waiting for a model.
    interpretation, planner, notice = interpret_goal(payload.goal, buildings, payload.use_model)
    proposal = _create_after_interpretation(session, drill_id, payload, interpretation, planner, notice, identity)
    if not payload.use_model or proposal['status'] != 'awaiting_approval' or not proposal.get('planning'):
        return proposal
    session.rollback()  # Provider calls must never retain a scene or resource lock.
    report = recommend(proposal, True)
    return _save_recommendation(session, drill_id, proposal['id'], proposal['revision'], report, identity)


@operations.serialized_command
def _save_recommendation(session, drill_id, run_id, revision, report, identity):
    drill, run = owned_run(session, drill_id, run_id, identity)
    session.execute(select(AgentRun.id).where(AgentRun.id == run.id).with_for_update())
    session.refresh(run)
    if run.revision == revision and run.status == 'awaiting_approval' and drill.status != 'ended':
        run.scope = {**run.scope, 'planning': report}
        if report['mode'] == 'model_tools':
            run.planner = 'model_tools'
        note(session, run, 'planning_checked', report['notice'], operations.effective_elapsed(drill))
        session.commit()
    return run_payload(session, run, operations.snapshot(session, drill))


@operations.serialized_command
def _create_after_interpretation(session, drill_id, payload, interpretation, planner, notice, identity):
    drill = operations.require_drill(session, drill_id, identity.username)
    session.execute(select(type(drill).id).where(type(drill).id == drill_id).with_for_update())
    existing = session.scalar(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.request_id == payload.request_id))
    if existing:
        validate_retry(existing, payload, identity.username)
        return run_payload(session, existing, operations.snapshot(session, drill))
    if drill.status not in {"running", "paused", "ready"}: raise HTTPException(409, "本场已结束，请新开一轮。")
    pause_review(session, drill, payload.pause_for_review)
    data = operations.snapshot(session, drill)
    scope = resolve_scope(data, payload, interpretation)
    scope.update(pause_for_review=payload.pause_for_review, include_case_tasks=payload.include_case_tasks)
    active = list(session.scalars(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.status.in_([*ACTIVE, "awaiting_rollcall"])) ))
    if len(active) >= 8:
        raise HTTPException(409, '本场已有 8 个活动计划，请先完成或停止一个，避免遗漏未处理目标。')
    if any(set(r.scope['resident_ids']).intersection(scope['resident_ids']) for r in active):
        raise HTTPException(409, '目标居民已有活动计划，请先调整或停止原计划；不同居民范围可独立编排。')
    scope["request_fingerprint"] = request_fingerprint(payload)
    candidates = build_candidates(session, drill, data, scope)
    from app.services.knowledge import retrieve
    from app.services.knowledge_applicability import situation
    from app.models.domain import Scene
    scene = session.get(Scene, drill.scene_id)
    parameters = data['simulation'].get('world', {}).get('parameters', {})
    scope['knowledge'] = retrieve(session, identity.username, payload.goal, community_id=scene.community_id,
        scenario='kitchen_fire' if parameters.get('fire_source_type') == 'kitchen' else 'charging_shed', drill_id=drill.id,
        situation=situation(data, scope))
    scope['planning'] = tool_report(data, scope, candidates)
    scope['planning']['knowledge_assessment'] = scope['knowledge']['assessment']
    scope['planning']['trace'].insert(1, {'tool': 'search_knowledge', 'label': '检索适用资料',
        'status': 'completed', 'summary': f"命中 {len(scope['knowledge']['hits'])} 条，引用内容与版本已保存"})
    scope['planning']['trace'].insert(2, {'tool': 'assess_knowledge', 'label': '核对经验适用条件',
        'status': 'completed', 'summary': scope['knowledge']['assessment']['notice']})
    run = AgentRun(id=str(uuid4()), drill_session_id=drill_id, request_id=payload.request_id, actor=identity.username,
                   goal=payload.goal, scope=scope, candidates=candidates, observed_sequence=data["latest_event_sequence"], planner=planner, planner_notice=notice,
                   reason="方案已计算，尚未执行；请核对范围与影响后确认。")
    session.add(run); session.flush()
    note(session, run, "proposed", f"已比较 {len(candidates)} 个方案，范围 {len(scope['resident_ids'])} 人。", data["elapsed_seconds"])
    session.commit()
    return run_payload(session, run, data)


@router.post("/drills/{drill_id}/agent/runs/{run_id}/actions")
def plan_action(drill_id: str, run_id: str, payload: PlanAction, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    proposal = _apply_plan_action(drill_id, run_id, payload, identity, session)
    if payload.action == 'replan' and payload.use_model and proposal['status'] == 'awaiting_approval' and proposal.get('planning'):
        session.rollback()
        report = recommend(proposal, True)
        return _save_recommendation(session, drill_id, run_id, proposal['revision'], report, identity)
    return proposal


@operations.serialized_command
def _apply_plan_action(drill_id, run_id, payload, identity, session):
    drill, run = owned_run(session, drill_id, run_id, identity)
    session.execute(select(type(drill).id).where(type(drill).id == drill_id).with_for_update())
    session.execute(select(AgentRun.id).where(AgentRun.id == run.id).with_for_update())
    session.refresh(run)
    if payload.action == "approve":
        approve(session, drill, run, payload.candidate_id, payload.revision, identity)
        advance_run(session, run, identity)
    elif payload.action == "review":
        if run.revision != payload.revision: raise HTTPException(409, "计划版本已变化，请重新读取。")
        if drill.status == "ended": raise HTTPException(409, "本场已结束，请新开一轮。")
        if run.status == "needs_review": return run_payload(session, run, operations.snapshot(session, drill))
        if run.status not in OPERATING: raise HTTPException(409, "当前计划不在自动执行中，不能调整剩余行动。")
        run.status, run.reason = "needs_review", "已暂停后续自动下令；已受理的人员与机器人行动继续。可按当前现场比较剩余行动，确认后接续执行。"
        run.revision += 1
        note(session, run, "review_requested", run.reason, operations.effective_elapsed(drill)); session.commit()
    elif payload.action == "stop":
        if run.revision != payload.revision: raise HTTPException(409, "计划版本已变化，请重新读取。")
        if run.status in {"completed", "stopped", "taken_over", "unfinished"}: return run_payload(session, run, operations.snapshot(session, drill))
        run.status, run.reason = "stopped", "已停止提交后续指令；已受理的人物行动仍继续，可在三维现场人工接管。"
        run.revision += 1
        from app.services.agent_claims import release
        release(session, run.id)
        note(session, run, "stopped", run.reason, operations.effective_elapsed(drill)); session.commit()
    else:
        if payload.revision != run.revision or run.status not in {"awaiting_approval", "needs_review"}: raise HTTPException(409, "请先停止或等待当前执行；已被人工接管的计划不能自动夺回控制。")
        from app.services.agent_contract import validate_goal_capabilities
        validate_goal_capabilities(run.goal)
        if drill.status == "ended": raise HTTPException(409, "本场已结束，请新开一轮。")
        pause_review(session, drill, run.scope.get('pause_for_review'))
        data = operations.snapshot(session, drill)
        from app.services.agent_revision import replan
        replan(session, drill, run, data, payload, identity)
    return run_payload(session, run, operations.snapshot(session, drill))
