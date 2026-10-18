"""Goal proposals and explicit approvals for the existing exercise command engine."""
from copy import deepcopy
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
from app.services.agent_resources import completed_broadcast
from app.services.agent_workflow import ACTIVE, OPERATING, advance_run, approve, buildings_for, build_candidates, note, resolve_scope, run_payload

router = APIRouter(tags=["goal workflows"])


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
    runs = session.scalars(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.actor == identity.username).order_by(AgentRun.created_at.desc()).limit(8)).all()
    return {"buildings": buildings_for(data), "runs": [run_payload(session, r, data) for r in runs], "drill_status": drill.status}


@router.post("/drills/{drill_id}/agent/runs", status_code=201)
def create_run(drill_id: str, payload: GoalCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    existing = session.scalar(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.request_id == payload.request_id))
    if existing:
        validate_retry(existing, payload, identity.username)
        return run_payload(session, existing, operations.snapshot(session, drill))
    if drill.status not in {"running", "paused", "ready"}: raise HTTPException(409, "本场已结束，请新开一轮再制定计划。")
    if not any(word in payload.goal for word in ("疏散", "撤离", "分流", "护送")):
        raise HTTPException(422, "当前目标计划支持居民疏散、分流和重点护送；其他问题请使用场景对话，车辆仍从车辆调度操作。")
    data = operations.snapshot(session, drill)
    buildings = buildings_for(data)
    session.rollback()  # No DB locks or open read transaction while waiting for a model.
    interpretation, planner, notice = interpret_goal(payload.goal, buildings, payload.use_model)
    return _create_after_interpretation(session, drill_id, payload, interpretation, planner, notice, identity)


@operations.serialized_command
def _create_after_interpretation(session, drill_id, payload, interpretation, planner, notice, identity):
    drill = operations.require_drill(session, drill_id, identity.username)
    session.execute(select(type(drill).id).where(type(drill).id == drill_id).with_for_update())
    existing = session.scalar(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.request_id == payload.request_id))
    if existing:
        validate_retry(existing, payload, identity.username)
        return run_payload(session, existing, operations.snapshot(session, drill))
    if drill.status not in {"running", "paused", "ready"}: raise HTTPException(409, "本场已结束，请新开一轮。")
    active = session.scalar(select(AgentRun).where(AgentRun.drill_session_id == drill_id, AgentRun.status.in_([*ACTIVE, "awaiting_rollcall"])))
    if active: raise HTTPException(409, "本场已有目标计划，请先完成、停止或修改现有计划。")
    data = operations.snapshot(session, drill)
    scope = resolve_scope(data, payload, interpretation)
    scope["request_fingerprint"] = request_fingerprint(payload)
    candidates = build_candidates(session, drill, data, scope)
    run = AgentRun(id=str(uuid4()), drill_session_id=drill_id, request_id=payload.request_id, actor=identity.username,
                   goal=payload.goal, scope=scope, candidates=candidates, observed_sequence=data["latest_event_sequence"], planner=planner, planner_notice=notice,
                   reason="方案已计算，尚未执行；请核对范围与影响后确认。")
    session.add(run); session.flush()
    note(session, run, "proposed", f"已比较 {len(candidates)} 个方案，范围 {len(scope['resident_ids'])} 人。", data["elapsed_seconds"])
    session.commit()
    return run_payload(session, run, data)


@router.post("/drills/{drill_id}/agent/runs/{run_id}/actions")
@operations.serialized_command
def plan_action(drill_id: str, run_id: str, payload: PlanAction, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill, run = owned_run(session, drill_id, run_id, identity)
    session.execute(select(AgentRun.id).where(AgentRun.id == run.id).with_for_update())
    session.refresh(run)
    if payload.action == "approve":
        approve(session, drill, run, payload.candidate_id, payload.revision, identity)
        advance_run(session, run, identity)
    elif payload.action == "stop":
        if run.revision != payload.revision: raise HTTPException(409, "计划版本已变化，请重新读取。")
        if run.status in {"completed", "stopped", "taken_over", "unfinished"}: return run_payload(session, run, operations.snapshot(session, drill))
        run.status, run.reason = "stopped", "已停止提交后续指令；已受理的人物行动仍继续，可在三维现场人工接管。"
        run.revision += 1
        note(session, run, "stopped", run.reason, operations.effective_elapsed(drill)); session.commit()
    else:
        if payload.revision != run.revision or run.status not in {"awaiting_approval", "needs_review"}: raise HTTPException(409, "请先停止或等待当前执行；已被人工接管的计划不能自动夺回控制。")
        if drill.status == "ended": raise HTTPException(409, "本场已结束，请新开一轮。")
        data = operations.snapshot(session, drill)
        remaining = [p["id"] for p in data["simulation"]["residents"] if p["id"] in run.scope["resident_ids"] and p["status"] != "evacuated"]
        evidence = completed_broadcast(session, run) if run.scope.get("robot_broadcast") else None
        if evidence:
            run.scope = {**run.scope, "robot_broadcast_evidence": evidence}
        if not remaining and (not run.scope.get("robot_broadcast") or evidence):
            people = [p for p in data["simulation"]["residents"] if p["id"] in run.scope["resident_ids"]]
            if run.scope["priority_assist"] and any(p["vulnerable"] and not p.get("assisted") for p in people):
                raise HTTPException(409, "目标已到场但重点人员未完成计划护送，请人工核对。")
            run.status = "completed" if all(p.get("counted") for p in people) else "awaiting_rollcall"
            run.reason = "目标已到场，行动证据已满足；请完成集合清点。" if run.status == "awaiting_rollcall" else "目标行动与集合核验已完成。"
            note(session, run, run.status, run.reason, data["elapsed_seconds"]); session.commit()
            return run_payload(session, run, data)
        scope = {**run.scope, "resident_ids": remaining}
        candidates = build_candidates(session, drill, data, scope)
        run.evidence = [*run.evidence, {"revision": run.revision, "steps": deepcopy(run.steps), "scope": deepcopy(run.scope)}]
        run.candidates, run.steps = candidates, []
        run.revision += 1; run.approved_revision = None; run.selected_candidate = None
        run.status, run.reason, run.observed_sequence = "awaiting_approval", "未到场部分已重新预演，请确认新版本。", data["latest_event_sequence"]
        note(session, run, "replanned", run.reason, data["elapsed_seconds"]); session.commit()
    return run_payload(session, run, operations.snapshot(session, drill))
