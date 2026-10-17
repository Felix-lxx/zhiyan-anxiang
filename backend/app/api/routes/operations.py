from __future__ import annotations

import math
import re
import socket
import hashlib
import secrets
from functools import wraps
from threading import RLock
from copy import deepcopy
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, authenticate_access_token, get_current_identity
from app.api.routes.scenes import owned_community
from app.core.database import SessionLocal, get_db
from app.models.domain import RoadEdge, RoadEdgeStatus, RoadNode, Scene, SceneStatus, SceneVersion
from app.models.operations import DrillCommand, DrillEngineLease, DrillEvent, DrillScore, DrillSession, DrillStateSnapshot, ParticipantSession, RobotAgent
from app.models.tasks import DecisionTask
from app.schemas.operations import BranchCompareRequest, DrillAction, DrillCreate, EventInject, ParticipantAction, ResidentCommand, RobotCommand, ParticipantHeartbeat, ParticipantJoin, TaskAction, TaskAssignment, DirectorConfig
from app.services.drill_simulation import plan_route, simulate_residents
from app.services.exercise_world import capture_world, frozen_world, projected_tasks
from app.schemas.operations import EditableBranchCreate, SearchAssignment
from app.schemas.operations import LiveCommand, VehicleCommand
from app.services.vehicle_dispatch import vehicle_runtime, plan_vehicle
from app.services.vehicle_rescue import rescue_projection, action_plan, ACTION_LABELS
from app.services.vehicle_traffic import protect_plan
from app.services.command_feedback import commit_changes, command_feedback
from app.services.command_ledger import apply_feedback, ledger_feedback, safe_arguments, same_command, synchronize_records
from app.services.realtime import live_snapshots, snapshot_patch, state_version
from app.services.state_store import load_snapshot, persist_snapshot


router = APIRouter(tags=["drill operations"])
PARTICIPANT_ONLINE_SECONDS = 25

# SQLite local deployment: serialize whole command transactions, not just inserts.
# Reentrant because director/engine commands reuse the same validated handlers.
_command_lock = RLock()


def serialized_command(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _command_lock:
            return function(*args, **kwargs)
    return wrapped


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def participant_identity(session: Session, drill: DrillSession, token: str | None, *, touch: bool = True) -> dict:
    digest = hashlib.sha256((token or "").encode()).hexdigest()
    record = session.scalar(select(ParticipantSession).where(
        ParticipantSession.drill_session_id == drill.id,
        ParticipantSession.token_hash == digest,
        ParticipantSession.left_at.is_(None),
    ))
    if record:
        if touch:
            record.last_seen_at = datetime.now(UTC)
        return {"participant_id": record.id, "role": record.role, "name": record.display_name}
    events = session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "participant.joined"))
    member = next((e.payload for e in events if secrets.compare_digest(e.payload.get("token_hash", ""), digest)), None)
    if not member:
        raise HTTPException(403, "请先登记参演身份；本场身份凭证缺失或无效。")
    record = ParticipantSession(
        id=member["participant_id"], drill_session_id=drill.id, role=member["role"],
        display_name=member["name"], token_hash=digest, last_seen_at=datetime.now(UTC),
    )
    session.add(record)
    session.flush()
    return {"participant_id": record.id, "role": record.role, "name": record.display_name}


def participant_presence_revision(session: Session, drill_id: str) -> int:
    sessions = list(session.scalars(select(ParticipantSession).where(
        ParticipantSession.drill_session_id == drill_id,
    )))
    if not sessions:
        return 0
    now = datetime.now(UTC)
    latest = max(int(aware(item.last_seen_at).timestamp()) for item in sessions)
    offline_count = sum(1 for item in sessions if item.left_at is not None or (now - aware(item.last_seen_at)).total_seconds() > PARTICIPANT_ONLINE_SECONDS)
    # Heartbeats advance the epoch component; each independent expiry also changes the suffix.
    return latest * 10_000 + min(offline_count, 9_999)


def validate_feedback(session: Session, drill: DrillSession, payload: ParticipantAction) -> None:
    world = frozen_world(session, drill)
    if not world:
        return
    if payload.action == "resource_ready" and payload.role != "物业/网格员":
        raise HTTPException(403, "资源就绪由物业处置组确认。")
    if payload.action == "resident_counted":
        if payload.role not in {"居民代表", "物业/网格员"}:
            raise HTTPException(403, "清点由居民代表或物业提交。")
        if not payload.resident_ids or not set(payload.resident_ids).issubset({p["id"] for p in world["residents"]}):
            raise HTTPException(422, "请明确选择本次已核验的居民，不能一键清除所有失联。")
        if world.get("schema_version", 2) >= 3:
            events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id)))
            state = simulation_state(drill, events, session=session)
            invalid = [p["label"] for p in state["residents"] if p["id"] in payload.resident_ids and p["status"] != "evacuated"]
            if invalid:
                raise HTTPException(409, "尚未到达集合点，不能清点："+"、".join(invalid))


@serialized_command
def advance_engine(session: Session, drill: DrillSession) -> None:
    """Reconcile monotonic milestones. Replay reads only recorded events, never ticks."""
    session.refresh(drill)
    if drill.status != "running" or not (world := frozen_world(session, drill)):
        return
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    types = {e.event_type for e in events}
    elapsed = effective_elapsed(drill)
    agent = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    if agent and "robot.inspection_started" not in types:
        target = world["inspection_target"]
        route, points, edges, distance, risks = plan_robot_route(session, drill, (agent.x, agent.y), (target["x"], target["y"]))
        append_event(session, drill, "robot.inspection_started", agent.name, "开始自动巡检：前往起火点附近连续采样。")
        append_event(session, drill, "robot.target_assigned", agent.name, "巡检目标：起火点复核", {"target": "起火点复核", "target_x": target["x"], "target_y": target["y"], "purpose": "inspection", "route": route, "route_points": points, "route_edge_ids": edges, "route_risks": risks, "planned_duration_seconds": max(8, round(distance / 3.5))})
    elif agent and "robot.alarm_confirmed" not in types:
        live = robot_runtime(agent, events, elapsed)
        target = world["inspection_target"]
        if math.dist((live["x"], live["y"]), (target["x"], target["y"])) <= 2:
            samples = [e for e in events if e.event_type == "robot.sensor_sample"]
            if not samples or elapsed - samples[-1].elapsed_seconds >= 2:
                from app.services.fire_environment import EnvironmentTimeline
                fire, _ = EnvironmentTimeline(world, [{"elapsed_seconds": e.elapsed_seconds, "sequence": e.sequence, "event_type": e.event_type, "payload": e.payload} for e in events]).at(elapsed)
                temperature = fire["temperature"]
                append_event(session, drill, "robot.sensor_sample", agent.name, f"火点近场采样 {len(samples) + 1}：温度 {temperature}℃（规则仿真）", {"temperature": temperature, "x": live["x"], "y": live["y"]})
                if len(samples) >= 2 and temperature >= 60 and all(e.payload.get("temperature", 0) >= 60 for e in samples[-2:]):
                    append_event(session, drill, "robot.alarm_confirmed", agent.name, "连续三次近场异常已确认，向指挥席上报并触发处置任务。", {"sample_count": len(samples) + 1, "x": live["x"], "y": live["y"]})
    confirmation = next((e for e in events if e.event_type == "robot.alarm_confirmed"), None)
    if confirmation:
        for task in world["tasks"]:
            if elapsed - confirmation.elapsed_seconds > task["deadline_seconds"] and not any(e.payload.get("task_id") == task["id"] and e.event_type in {"task.completed", "task.overdue"} for e in events):
                append_event(session, drill, "task.overdue", "演练引擎", f"{task['title']}已超时；后续仍可补救，但不计按时完成得分。", {"task_id": task["id"], "consequence": "timeliness_credit_lost"})
    configured = next((e for e in reversed(events) if e.event_type == "director.configured"), None)
    last = max((e.elapsed_seconds for e in events if e.event_type == "director.cue"), default=configured.elapsed_seconds if configured else 0)
    if configured and configured.payload.get("enabled") and elapsed - last >= 14:
        # The endpoint owns event validation; the scheduler uses the same implementation.
        scene = session.get(Scene, drill.scene_id)
        from app.models.domain import Community, User
        community = session.get(Community, scene.community_id)
        username = session.get(User, community.owner_id).username
        advance_director(drill.id, SimpleNamespace(username=username), session)
    reconcile_vehicle_services(session, drill)
    record_vehicle_arrivals(session, drill)
    ledger_events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    ledger_simulation = simulation_state(drill, ledger_events, effective_elapsed(drill), session=session)
    ledger_robot = robot_runtime(agent, ledger_events, effective_elapsed(drill))
    synchronize_records(
        session,
        drill,
        command_feedback(ledger_events, ledger_simulation, ledger_robot, effective_elapsed(drill), drill.status),
        effective_elapsed(drill),
    )
    persist_snapshot(session, drill, snapshot(session, drill), force=drill.status != "running")
    commit_changes(session)


@router.post("/participant/drills/{drill_id}/join")
@serialized_command
def join_participant(drill_id: str, code: str, payload: ParticipantJoin, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    if drill.status == "ended":
        raise HTTPException(409, "本场已结束，不能登记新参演身份。")
    if payload.role not in {p["role"] for p in drill.participants} - {"演练总控/导演"}:
        raise HTTPException(422, "无效参演角色。")
    token = secrets.token_urlsafe(32)
    record = ParticipantSession(
        drill_session_id=drill.id, role=payload.role, display_name=payload.display_name,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    session.add(record)
    session.flush()
    member = {"participant_id": record.id, "role": record.role, "name": record.display_name, "token_hash": record.token_hash}
    append_event(session, drill, "participant.joined", payload.role, f"{payload.display_name}登记加入，身份固定为{payload.role}。", member)
    commit_changes(session)
    return {"token": token, "role": record.role, "name": record.display_name, "participant_id": record.id}


@router.post("/participant/drills/{drill_id}/heartbeat")
@serialized_command
def participant_heartbeat(drill_id: str, code: str, payload: ParticipantHeartbeat, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    member = participant_identity(session, drill, payload.participant_token)
    session.commit()
    return {**member, "online": True, "server_time": datetime.now(UTC).isoformat()}


@router.post("/participant/drills/{drill_id}/leave")
@serialized_command
def leave_participant(drill_id: str, code: str, payload: ParticipantHeartbeat, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    member = participant_identity(session, drill, payload.participant_token, touch=False)
    record = session.get(ParticipantSession, member["participant_id"])
    if record:
        record.left_at = datetime.now(UTC)
        session.commit()
    return {"participant_id": member["participant_id"], "online": False}


@serialized_command
def perform_task(session: Session, drill: DrillSession, task_id: str, payload: TaskAction, member: dict) -> dict:
    if drill.status != "running":
        raise HTTPException(409, "只有运行中的场次可以处置任务。")
    advance_engine(session, drill)
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    data = snapshot(session, drill)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task or data["engine_version"] < 2:
        raise HTTPException(404, "未找到新版场次任务。")
    if member["role"] != task["responsible_role"]:
        raise HTTPException(403, f"此任务由{task['responsible_role']}负责。")
    if task.get("assignee_id") and task["assignee_id"] != member["participant_id"]:
        raise HTTPException(409, "该任务已由其他参演人员接收，请协作沟通，不可覆盖。")
    if task["status"] == "waiting":
        raise HTTPException(409, "等待机器人确认火情后触发任务。")
    if task["status"] == "completed":
        return data
    if payload.action == "accept" and task["status"] != "pending":
        return data
    if payload.action == "arrive" and task["status"] == "verifying":
        return data
    if payload.action == "arrive" and task["status"] != "executing":
        raise HTTPException(409, "请先接收此任务。")
    if payload.action == "submit":
        if not task["can_submit"]:
            raise HTTPException(409, "；".join(task["blockers"]))
        if len(payload.evidence.strip()) < 6:
            raise HTTPException(422, "请填写至少 6 个字的处置结果证据。")
    kind = {"accept": "accepted", "arrive": "arrived", "submit": "completed"}[payload.action]
    label = {"accept": "已接收", "arrive": "已回执到位", "submit": "核验完成"}[payload.action]
    append_event(session, drill, f"task.{kind}", member["name"], f"{task['title']}：{label}", {"task_id": task_id, "kind": task["kind"], "participant_id": member["participant_id"], "role": member["role"], "evidence": payload.evidence.strip(), "target_object_id": task["target_object_id"]})
    commit_changes(session)
    return snapshot(session, drill)


@router.post("/participant/drills/{drill_id}/tasks/{task_id}/actions")
@serialized_command
def participant_task_action(drill_id: str, task_id: str, code: str, payload: TaskAction, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    return perform_task(session, drill, task_id, payload, participant_identity(session, drill, payload.participant_token))


@router.post("/drills/{drill_id}/tasks/{task_id}/actions")
@serialized_command
def director_task_action(drill_id: str, task_id: str, payload: TaskAction, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    task = next((t for t in (frozen_world(session, drill) or {}).get("tasks", []) if t["id"] == task_id), None)
    if not task:
        raise HTTPException(404, "未找到任务。")
    return perform_task(session, drill, task_id, payload, {"participant_id": "director:" + identity.username, "name": "总控代办：" + identity.username, "role": task["responsible_role"]})


@router.post("/drills/{drill_id}/tasks/{task_id}/assign")
@serialized_command
def assign_task(drill_id: str, task_id: str, payload: TaskAssignment, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(409, "只有运行中的演练可以指派任务。")
    data = snapshot(session, drill)
    task = next((item for item in data["tasks"] if item["id"] == task_id), None)
    if not task or data["engine_version"] < 2:
        raise HTTPException(404, "未找到可指派的场次任务。")
    if task["status"] not in {"waiting", "pending"} or task.get("assignment_locked"):
        raise HTTPException(409, "任务已被接收或进入处置阶段，不能重新指派。")
    member = session.scalar(select(ParticipantSession).where(
        ParticipantSession.id == payload.participant_id,
        ParticipantSession.drill_session_id == drill.id,
        ParticipantSession.left_at.is_(None),
    ))
    if not member:
        raise HTTPException(404, "参演成员已离开本场，请刷新在线列表后重新选择。")
    if member.role != task["responsible_role"]:
        raise HTTPException(422, f"该任务只能指派给{task['responsible_role']}。")
    if (datetime.now(UTC) - aware(member.last_seen_at)).total_seconds() > PARTICIPANT_ONLINE_SECONDS:
        raise HTTPException(409, "该成员当前离线，请选择在线成员或等待其重新连接。")
    if task.get("assignee_id") == member.id:
        return data
    append_event(session, drill, "task.assigned", member.display_name, f"{task['title']}已指派给{member.display_name}。", {
        "task_id": task_id, "participant_id": member.id, "role": member.role,
        "assigned_name": member.display_name, "assigned_by": identity.username,
    })
    commit_changes(session)
    return snapshot(session, drill)


@router.patch("/drills/{drill_id}/director/config")
@serialized_command
def configure_director(drill_id: str, payload: DirectorConfig, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status == "ended":
        raise HTTPException(409, "已结束场次不能改变自动事件配置。")
    append_event(session, drill, "director.configured", identity.username, "自动事件导演已" + ("启用" if payload.enabled else "停用"), payload.model_dump())
    commit_changes(session)
    return snapshot(session, drill)


@router.post("/drills/{drill_id}/roads/{edge_id}/reopen")
@serialized_command
def reopen_road(drill_id: str, edge_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(409, "只有运行中可解除封锁。")
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill_id)))
    edge = next((e for e in road_network_state(session, drill, events)["edges"] if e["id"] == edge_id), None)
    if not edge:
        raise HTTPException(404, "未找到本场次道路。")
    if edge["status"] == "blocked":
        append_event(session, drill, "road.reopened", identity.username, edge["name"] + "已解除封锁，重新计算路径。", {"blocked_edge_id": edge_id})
        robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
        if robot:
            replan_robot_queue(session, drill, robot, "道路恢复通行，重算未完成任务。")
        replan_vehicle_fleet(session, drill)
        commit_changes(session)
    return snapshot(session, drill)

PARTICIPANTS = [
    {"role": "演练总控/导演", "name": "总控席", "ready": True},
    {"role": "应急指挥人员", "name": "社区指挥", "ready": True},
    {"role": "物业/网格员", "name": "物业处置组", "ready": True},
    {"role": "居民代表", "name": "3 号楼居民组", "ready": True},
]


def effective_elapsed(drill: DrillSession) -> int:
    elapsed = drill.elapsed_seconds
    if drill.status == "running" and drill.started_at:
        started = drill.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed += int((datetime.now(UTC) - started).total_seconds() * drill.time_scale)
    return max(0, elapsed)


def append_event(session: Session, drill: DrillSession, event_type: str, actor: str, message: str, payload: dict | None = None) -> DrillEvent:
    session.execute(select(DrillSession.id).where(DrillSession.id == drill.id).with_for_update())
    sequence = (session.scalar(select(func.max(DrillEvent.sequence)).where(DrillEvent.drill_session_id == drill.id)) or 0) + 1
    event = DrillEvent(drill_session_id=drill.id, sequence=sequence, event_type=event_type, actor=actor, message=message, payload=payload or {}, elapsed_seconds=effective_elapsed(drill))
    session.add(event)
    # Subsequent events and route planners in this transaction must see this evidence.
    session.flush()
    return event


def plan_robot_route(
    session: Session,
    drill: DrillSession,
    start: tuple[float, float],
    target: tuple[float, float],
) -> tuple[list[str], list[dict], list[str], float, list[dict]]:
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    elapsed = effective_elapsed(drill)
    network = road_network_state(session, drill, events)
    world = frozen_world(session, drill)
    if world and world.get("schema_version", 2) >= 3:
        evidence = [{"sequence": event.sequence, "elapsed_seconds": event.elapsed_seconds, "event_type": event.event_type, "payload": event.payload} for event in events]
        live_network = simulate_residents(network, evidence, elapsed, world=world)["road_network"]
        live_network["fire_origin"] = network.get("fire_origin", world["fire_origin"])
        live_network["obstacles"] = network.get("obstacles", [])
        network = live_network
    return plan_route(network, start, target, elapsed)


def route_position(points: list[dict], progress: float) -> tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if len(points) == 1:
        return float(points[0]["x"]), float(points[0]["y"])
    lengths = [math.dist((points[index]["x"], points[index]["y"]), (points[index + 1]["x"], points[index + 1]["y"])) for index in range(len(points) - 1)]
    total = sum(lengths)
    remaining = max(0.0, min(1.0, progress)) * total
    for index, length in enumerate(lengths):
        if remaining <= length or index == len(lengths) - 1:
            local = 0.0 if length == 0 else remaining / length
            return (
                points[index]["x"] + (points[index + 1]["x"] - points[index]["x"]) * local,
                points[index]["y"] + (points[index + 1]["y"] - points[index]["y"]) * local,
            )
        remaining -= length
    return float(points[-1]["x"]), float(points[-1]["y"])


def nearest_road_edge(session: Session, drill: DrillSession, point: tuple[float, float]) -> tuple[RoadEdge, float]:
    world = frozen_world(session, drill)
    if world and world["road_network"]["edges"]:
        def distance(edge):
            a, b = edge["start"], edge["end"]
            dx, dy = b["x"] - a["x"], b["y"] - a["y"]
            t = max(0, min(1, ((point[0] - a["x"]) * dx + (point[1] - a["y"]) * dy) / max(1e-9, dx * dx + dy * dy)))
            return math.dist(point, (a["x"] + t * dx, a["y"] + t * dy))
        edge = min(world["road_network"]["edges"], key=distance)
        return road_edge_for_drill(session, drill, edge["id"]), distance(edge)
    version = session.get(SceneVersion, drill.scene_version_id)
    if version is None:
        raise HTTPException(status_code=422, detail="场景缺少社区道路版本。")
    nodes = {node.id: node for node in session.scalars(select(RoadNode).where(RoadNode.community_version_id == version.community_version_id))}
    edges = list(session.scalars(select(RoadEdge).where(RoadEdge.community_version_id == version.community_version_id)))
    if not edges:
        raise HTTPException(status_code=422, detail="场景尚未建立道路图。")

    def segment_distance(edge: RoadEdge) -> float:
        start, end = nodes[edge.start_node_id], nodes[edge.end_node_id]
        dx, dy = end.x - start.x, end.y - start.y
        denominator = dx * dx + dy * dy
        projection = 0 if denominator == 0 else max(0, min(1, ((point[0] - start.x) * dx + (point[1] - start.y) * dy) / denominator))
        return math.dist(point, (start.x + projection * dx, start.y + projection * dy))

    edge = min(edges, key=segment_distance)
    return edge, segment_distance(edge)


def road_edge_for_drill(session: Session, drill: DrillSession, edge_id: str) -> RoadEdge:
    world = frozen_world(session, drill)
    if world:
        edge = next((e for e in world["road_network"]["edges"] if e["id"] == edge_id), None)
        if not edge:
            raise HTTPException(422, "该道路不属于本场次冻结地图。")
        return SimpleNamespace(**{**edge, "status": RoadEdgeStatus(edge["status"])})
    version = session.get(SceneVersion, drill.scene_version_id)
    edge = session.get(RoadEdge, edge_id)
    if version is None or edge is None or edge.community_version_id != version.community_version_id:
        raise HTTPException(status_code=422, detail="选择的道路不属于当前演练社区。")
    return edge


def road_network_state(session: Session, drill: DrillSession, events: list[DrillEvent]) -> dict:
    world = frozen_world(session, drill)
    if world:
        network = deepcopy(world["road_network"])
        for event in sorted(events, key=lambda e: e.sequence):
            if event.event_type in {"inject.channel_blocked", "road.reopened"}:
                for edge in network["edges"]:
                    if edge["id"] == event.payload.get("blocked_edge_id"):
                        edge["status"] = "blocked" if event.event_type == "inject.channel_blocked" else "open"
                        edge["blocked_by_event"] = edge["status"] == "blocked"
        network["fire_origin"] = world["fire_origin"]
        network["obstacles"] = [{"x": o["x"], "y": o["y"], "width": o["width"], "depth": o["depth"]} for o in world["objects"] if o["type"] == "building"]
        return network
    version = session.get(SceneVersion, drill.scene_version_id)
    if version is None:
        return {"nodes": [], "edges": []}
    nodes = list(session.scalars(select(RoadNode).where(RoadNode.community_version_id == version.community_version_id)))
    edges = list(session.scalars(select(RoadEdge).where(RoadEdge.community_version_id == version.community_version_id)))
    node_by_id = {node.id: node for node in nodes}
    blocked_edge_ids = {
        event.payload.get("blocked_edge_id")
        for event in events
        if event.event_type == "inject.channel_blocked" and event.payload.get("blocked_edge_id")
    }
    edge_items = []
    for edge in edges:
        start, end = node_by_id.get(edge.start_node_id), node_by_id.get(edge.end_node_id)
        if start is None or end is None:
            continue
        midpoint = ((start.x + end.x) / 2, (start.y + end.y) / 2)
        fire_distance = math.dist(midpoint, (66, 43))
        fire_risk = max(0.0, 24 - fire_distance) / 24
        width_risk = min(1.0, 3.5 / max(1.0, edge.width_meters))
        effective_status = "blocked" if edge.id in blocked_edge_ids or edge.status == RoadEdgeStatus.BLOCKED else edge.status.value
        risk_score = min(100, round((fire_risk * .65 + width_risk * .35) * 100 + (25 if effective_status == "restricted" else 100 if effective_status == "blocked" else 0)))
        edge_items.append({
            "id": edge.id,
            "name": edge.name,
            "start_node_id": edge.start_node_id,
            "end_node_id": edge.end_node_id,
            "start": {"x": start.x, "y": start.y},
            "end": {"x": end.x, "y": end.y},
            "width_meters": edge.width_meters,
            "status": effective_status,
            "blocked_by_event": edge.id in blocked_edge_ids,
            "risk_score": risk_score,
        })
    return {
        "nodes": [{"id": node.id, "name": node.name, "x": node.x, "y": node.y, "is_exit": node.is_exit} for node in nodes],
        "edges": edge_items,
    }


def participant_code(drill_id: str) -> str:
    return drill_id.replace("-", "")[-6:].upper()


def require_participant_drill(session: Session, drill_id: str, code: str) -> DrillSession:
    drill = session.get(DrillSession, drill_id)
    if drill is None or code.upper() != participant_code(drill_id):
        raise HTTPException(status_code=404, detail="参演链接无效或场次不存在。")
    return drill


def require_drill(session: Session, drill_id: str, username: str) -> DrillSession:
    drill = session.get(DrillSession, drill_id)
    if drill is None:
        raise HTTPException(status_code=404, detail="未找到该演练场次。")
    scene = session.get(Scene, drill.scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到演练关联场景。")
    owned_community(session, scene.community_id, username)
    return drill


def calculate_score_data(session: Session, drill: DrillSession, events: list[DrillEvent] | None = None, simulation: dict | None = None) -> dict:
    world = frozen_world(session, drill)
    if world:
        history = events if events is not None else list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
        sim = simulation or simulation_state(drill, history, session=session)
        completed = {e.payload.get("task_id"): e for e in history if e.event_type == "task.completed"}
        total = max(1, sim["summary"]["total"])
        alarm = next((e for e in history if e.event_type == "robot.alarm_confirmed"), None)
        acknowledgement = next((e for e in history if e.event_type == "participant.acknowledge" and alarm and e.elapsed_seconds >= alarm.elapsed_seconds), None)
        timely = sum(t["id"] in completed and alarm is not None and completed[t["id"]].elapsed_seconds - alarm.elapsed_seconds <= t["deadline_seconds"] for t in world["tasks"])
        vulnerable = [p for p in sim["residents"] if p["vulnerable"]]
        criteria = [
            ("疏散结果", round((20 * sim["summary"]["evacuated"] + 10 * sim["summary"].get("counted", sim["summary"]["evacuated"])) / total), 30, "participant.resident_counted" if world.get("schema_version", 2) >= 3 else "resident.command", f"已到达 {sim['summary']['evacuated']}/{total} 人；已核验 {sim['summary'].get('counted', sim['summary']['evacuated'])}/{total} 人"),
            ("烟气与失联控制", max(0, round(20 * (1 - (sim["summary"]["smoke_exposed"] + sim["summary"]["missing"]) / total))), 20, "resident.command", f"暴露 {sim['summary']['smoke_exposed']} 人；失联 {sim['summary']['missing']} 人"),
            ("按时核验处置", round(25 * timely / max(1, len(world["tasks"]))), 25, "task.completed", f"按时完成 {timely}/{len(world['tasks'])} 项，超时完成仍留证但不计此项"),
            ("重点人员护送", round(10 * sum(p["status"] == "evacuated" and p.get("assisted") for p in vulnerable) / max(1, len(vulnerable))), 10, "resident.command", "只计算护送到达，不按下达指令次数计分"),
            ("感知与响应", (5 if alarm else 0) + (5 if acknowledgement and acknowledgement.elapsed_seconds - alarm.elapsed_seconds <= 30 else 0), 10, "robot.alarm_confirmed", "连续采样确认后 30 秒内回执告警"),
            ("演练完整性", 5 if any(e.event_type == "drill.ended" for e in history) else 0, 5, "drill.ended", "场次结束并冻结结果"),
        ]
        details = [{"name": name, "score": value, "max_score": maximum, "evidence": explanation, "event_ids": [e.id for e in history if e.event_type == kind], "at_seconds": next((e.elapsed_seconds for e in reversed(history) if e.event_type == kind), 0)} for name, value, maximum, kind, explanation in criteria]
        return {"version": 2, "total_score": sum(d["score"] for d in details), "details": details, "recommendations": [d["name"] + "：" + d["evidence"] for d in details if d["score"] < d["max_score"]] or ["本轮所有结果指标已达标，可调整扰动重新验证。"]}
    events = events if events is not None else list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id)))
    event_types = {event.event_type for event in events}
    completed_tasks = {event.payload.get("task_id") for event in events if event.event_type == "task.completed"}
    total_tasks = session.scalar(select(func.count(DecisionTask.id)).where(DecisionTask.scene_version_id == drill.scene_version_id)) or 0
    simulation = simulation if simulation is not None else simulation_state(drill, events, session=session)
    safety_score = max(0, 10 - min(10, simulation["summary"]["smoke_exposed"] // 2 + simulation["summary"]["missing"] * 3))
    participant_roles = {event.actor for event in events if event.event_type.startswith("participant.") and event.event_type != "participant.joined"}
    resident_commands = [event for event in events if event.event_type == "resident.command"]
    exact_block = any(event.event_type == "inject.channel_blocked" and event.payload.get("blocked_edge_id") for event in events)
    valid_replan = any(event.event_type == "robot.replanned" and len(event.payload.get("route_points", [])) > 1 and event.payload.get("route_edge_ids") for event in events)
    task_score = 12 if completed_tasks and (not total_tasks or len(completed_tasks) >= total_tasks) else min(12, len(completed_tasks) * 6)
    details = [
        {"name": "响应启动", "score": 8 if "drill.started" in event_types else 0, "max_score": 8, "evidence": "drill.started"},
        {"name": "空间道路处置", "score": 10 if exact_block else 0, "max_score": 10, "evidence": "inject.channel_blocked.blocked_edge_id"},
        {"name": "真实路径改道", "score": 15 if valid_replan else 0, "max_score": 15, "evidence": "robot.replanned.route_points+route_edge_ids"},
        {"name": "具身任务闭环", "score": 15 if "robot.broadcast_completed" in event_types else 0, "max_score": 15, "evidence": "robot.broadcast_completed"},
        {"name": "处置任务完成", "score": task_score, "max_score": 12, "evidence": f"task.completed={len(completed_tasks)}/{total_tasks}"},
        {"name": "居民分流与护送", "score": 15 if resident_commands else 0, "max_score": 15, "evidence": f"resident.command={len(resident_commands)}"},
        {"name": "多人协同反馈", "score": min(10, len(participant_roles) * 5), "max_score": 10, "evidence": f"participant.roles={len(participant_roles)}"},
        {"name": "人员安全结果", "score": safety_score, "max_score": 10, "evidence": f"smoke_exposed={simulation['summary']['smoke_exposed']},missing={simulation['summary']['missing']}"},
        {"name": "演练完整性", "score": 5 if "drill.ended" in event_types else 0, "max_score": 5, "evidence": "drill.ended"},
    ]
    for item in details:
        item.setdefault("max_score", item["score"] if item["score"] else 15)
    total = sum(item["score"] for item in details)
    recommendations = []
    if not exact_block:
        recommendations.append("在三维现场直接选择具体道路路段完成封锁，保留路段编号证据。")
    if not valid_replan:
        recommendations.append("增加道路封锁后的机器人改道演示，并保留原因证据。")
    if "robot.broadcast_completed" not in event_types:
        recommendations.append("在结束演练前完成机器人广播任务闭环。")
    if "resident.command" not in event_types:
        recommendations.append("在三维现场选择居民并完成分流或重点护送，降低拥堵和烟气暴露。")
    if not any(event_type.startswith("participant.") for event_type in event_types):
        recommendations.append("邀请手机参演端提交到岗、物资或清点反馈，形成多人协同证据。")
    if not recommendations:
        recommendations.append("本轮闭环完整，可在下一轮缩短响应时间并对比得分。")
    return {"total_score": total, "details": details, "recommendations": recommendations}


def score_drill(session: Session, drill: DrillSession) -> DrillScore:
    existing = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
    if existing:
        return existing
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    simulation = simulation_state(drill, events, session=session)
    data = calculate_score_data(session, drill, events, simulation)
    ended_event = next((event for event in reversed(events) if event.event_type == "drill.ended"), None)
    if ended_event:
        completed_task_ids = {event.payload.get("task_id") for event in events if event.event_type == "task.completed"}
        total_tasks = session.scalar(select(func.count(DecisionTask.id)).where(DecisionTask.scene_version_id == drill.scene_version_id)) or 0
        ended_event.payload = {
            **ended_event.payload,
            "final_summary": simulation["summary"],
            "task_summary": {"completed": len(completed_task_ids), "total": total_tasks},
        }
    score = DrillScore(drill_session_id=drill.id, total_score=data["total_score"], details=data["details"], recommendations=data["recommendations"])
    session.add(score)
    return score


def simulation_state(
    drill: DrillSession,
    events: list[DrillEvent],
    elapsed_override: int | None = None,
    session: Session | None = None,
    strategy: str | None = None,
    branch_at: int | None = None,
) -> dict:
    elapsed = effective_elapsed(drill) if elapsed_override is None else elapsed_override
    network = road_network_state(session, drill, []) if session is not None else {"nodes": [], "edges": []}
    evidence = [{"sequence": event.sequence, "elapsed_seconds": event.elapsed_seconds, "event_type": event.event_type, "payload": event.payload} for event in events]
    world = frozen_world(session, drill) if session else None
    if session and world and world.get("schema_version", 0) >= 3 and not strategy:
        from app.services.state_store import restore_engine_checkpoint
        restore_engine_checkpoint(session, drill.id, world, elapsed)
    simulation = simulate_residents(network, evidence, elapsed, strategy, branch_at if branch_at is not None else effective_elapsed(drill) if strategy else None, world)
    state = rescue_projection(world, events, elapsed, vehicle_runtime(world, events, elapsed), simulation)
    state["rescue_projection_version"] = 1
    for vehicle in state["vehicles"]:
        if vehicle["state"] == "yielding":
            occupants = [p for p in state["residents"] if p.get("current_edge_id") in vehicle["route_edge_ids"]]
            helpers = [h for h in state.get("helpers", []) if h.get("edge_id") in vehicle["route_edge_ids"]]
            vehicle["waiting_people"] = len(occupants) + len(helpers)
            names = "、".join(p["label"] for p in occupants[:3])
            vehicle["reason"] = f"通道内还有 {vehicle['waiting_people']} 人" + (f"（{names}）" if names else "") + "；入口已暂停放行，清空后自动出发。"
            if any(p["status"] == "missing" for p in occupants):
                vehicle["reason"] += "其中有失联人员，请先安排搜索会合，或取消行程后改选目标。"
        vehicle["service_options"] = {action: action_plan(world, state, vehicle, action) for action in (["spray"] if vehicle["kind"] == "firetruck" else ["handover"])}
    state["transfer_candidates"] = [{"id": p["id"], "label": p["label"], "exit": p.get("exit"), "eligible": bool(p.get("counted")),
                                     "reason": "已核验，可以接运" if p.get("counted") else "先在集合点完成清点"}
                                    for p in state["residents"] if p["status"] == "evacuated" and not p.get("medical_transfer") and (p["vulnerable"] or p.get("smoke_exposure", 0) > 5)]
    return state


def vehicle_state(session: Session, drill: DrillSession):
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    return events, simulation_state(drill, events, session=session)


def replan_vehicle_fleet(session: Session, drill: DrillSession):
    _, state = vehicle_state(session, drill)
    for vehicle in state["vehicles"]:
        if vehicle["state"] not in {"moving", "blocked", "yielding"}:
            continue
        plan = protect_plan(plan_vehicle(state["road_network"], vehicle, vehicle["target_node_id"]), state, vehicle["id"])
        append_event(session, drill, "vehicle.replanned", "演练引擎", f"{vehicle['name']}：道路变化后从当前位置重新规划。",
                     {**plan, "vehicle_id": vehicle["id"], "mission_id": vehicle["mission_id"]})
        _, state = vehicle_state(session, drill)


def record_vehicle_arrivals(session: Session, drill: DrillSession):
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id)))
    recorded = {e.payload.get("mission_id") for e in events if e.event_type == "vehicle.arrived"}
    for vehicle in vehicle_runtime(frozen_world(session, drill), events, effective_elapsed(drill)):
        if vehicle["state"] == "arrived" and vehicle["mission_id"] not in recorded:
            append_event(session, drill, "vehicle.arrived", "演练引擎", f"{vehicle['name']}已到达{vehicle['target_name']}。",
                         {"vehicle_id": vehicle["id"], "mission_id": vehicle["mission_id"], "target_node_id": vehicle["target_node_id"], "x": vehicle["x"], "y": vehicle["y"]})


def reconcile_vehicle_services(session: Session, drill: DrillSession):
    """Only the engine/command transaction emits completions; projections stay read-only."""
    events, state = vehicle_state(session, drill)
    elapsed = effective_elapsed(drill)
    for vehicle in state["vehicles"]:
        if vehicle["state"] == "yielding":
            if not any(e.get("live_occupancy", 0) for e in state["road_network"]["edges"] if e["id"] in vehicle["route_edge_ids"]):
                append_event(session, drill, "vehicle.traffic_released", "演练引擎", f"{vehicle['name']}通道人员已清空，开始通行。",
                             {"vehicle_id": vehicle["id"], "mission_id": vehicle["mission_id"], "planned_duration_seconds": vehicle["planned_duration_seconds"]})
        service = vehicle.get("service")
        if not service: continue
        failed_water = service["action"] == "spray" and state["environment"]["east_hydrant"] == "failed"
        if failed_water or elapsed >= service["ends_at_seconds"]:
            kind = "vehicle.action_stopped" if failed_water else "vehicle.action_completed"
            message = "水源中断，喷水停止，请调整供水方案" if failed_water else f"{service['label']}完成"
            append_event(session, drill, kind, "演练引擎", f"{vehicle['name']}：{message}。",
                         {"action_id": service["action_id"], "vehicle_id": vehicle["id"], "action": service["action"], "resident_id": service.get("resident_id"),
                          "effective_seconds": min(service["duration_seconds"], max(0, elapsed - service["starts_at_seconds"])), "fire_intensity": state["fire"]["intensity"]})


@router.post("/drills/{drill_id}/vehicles/preview")
def preview_vehicle(drill_id: str, payload: VehicleCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(409, "请先运行演练，再安排车辆。")
    events, state = vehicle_state(session, drill)
    vehicle = next((v for v in state["vehicles"] if v["id"] == payload.vehicle_id), None)
    if vehicle is None:
        raise HTTPException(404, "本场次尚无可调度车辆或路网。")
    if payload.command in ACTION_LABELS:
        plan = action_plan(frozen_world(session, drill), state, vehicle, payload.command, payload.resident_id)
        return {**plan, "planned_duration_seconds": plan["duration_seconds"], "kind": "vehicle", "title": f"{vehicle['name']} · {ACTION_LABELS[payload.command]}",
                "expected_sequence": max((e.sequence for e in events), default=0), "route_points": plan.get("pickup_points", []), "rescue_action": payload.command}
    if payload.command != "dispatch" or not payload.target_node_id:
        raise HTTPException(422, "请选择车辆到场的道路节点。")
    plan = protect_plan(plan_vehicle(state["road_network"], vehicle, payload.target_node_id), state, vehicle["id"])
    if vehicle["state"] in {"moving", "blocked", "yielding"} or vehicle.get("service"):
        plan.update(can_apply=False, notice="该车已有行程，请先取消或重新规划当前行程。")
    if vehicle.get("passenger") and not any(n["id"] == payload.target_node_id and n["is_exit"] for n in state["road_network"]["nodes"]):
        plan.update(can_apply=False, notice="车内有人，请选择出口医疗接应点。")
    return {**plan, "kind": "vehicle", "title": f"{vehicle['name']} → {plan['target_name']}", "vehicle_id": vehicle["id"],
            "expected_sequence": max((e.sequence for e in events), default=0)}


@router.post("/drills/{drill_id}/vehicles")
@serialized_command
def command_vehicle(drill_id: str, payload: VehicleCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(409, "演练运行时才能调度车辆。")
    reconcile_vehicle_services(session, drill)
    record_vehicle_arrivals(session, drill)
    _, state = vehicle_state(session, drill)
    vehicle = next((v for v in state["vehicles"] if v["id"] == payload.vehicle_id), None)
    if vehicle is None:
        raise HTTPException(404, "没有找到本场次车辆。")
    active = vehicle["state"] in {"moving", "blocked", "yielding"}
    if payload.command in ACTION_LABELS:
        plan = action_plan(frozen_world(session, drill), state, vehicle, payload.command, payload.resident_id)
        if not plan["can_apply"]: raise HTTPException(409, plan["notice"])
        append_event(session, drill, "vehicle.action_started", identity.username, f"{vehicle['name']}开始{ACTION_LABELS[payload.command]}。",
                     {**plan, "action_id": secrets.token_hex(16), "vehicle_id": vehicle["id"]})
        commit_changes(session)
        return snapshot(session, drill)
    if payload.command == "stop_action":
        service = vehicle.get("service")
        if not service: raise HTTPException(409, "当前没有进行中的到场处置。")
        if service["action"] != "spray": raise HTTPException(409, "接运或移交正在进行，请等待人员交接完成。")
        append_event(session, drill, "vehicle.action_stopped", identity.username, f"{vehicle['name']}停止{service['label']}，保留已发生的处置效果。",
                     {"action_id": service["action_id"], "vehicle_id": vehicle["id"], "action": service["action"], "resident_id": service.get("resident_id")})
        commit_changes(session)
        return snapshot(session, drill)
    if vehicle.get("service"): raise HTTPException(409, "请先结束到场处置，再安排车辆行程。")
    if payload.command == "dispatch":
        if active:
            raise HTTPException(409, "该车正在执行行程，请先取消或重算当前路线。")
        if vehicle.get("passenger") and not any(n["id"] == payload.target_node_id and n["is_exit"] for n in state["road_network"]["nodes"]):
            raise HTTPException(409, "车内载有人员，请选择出口医疗接应节点。")
        plan = protect_plan(plan_vehicle(state["road_network"], vehicle, payload.target_node_id or ""), state, vehicle["id"])
        if not plan["can_apply"]:
            raise HTTPException(409, plan["notice"])
        append_event(session, drill, "vehicle.dispatched", identity.username, f"{vehicle['name']}前往{plan['target_name']}。", {**plan, "vehicle_id": vehicle["id"]})
    elif not active:
        raise HTTPException(409, "车辆没有进行中的行程。")
    elif payload.command == "cancel":
        if vehicle.get("passenger"): raise HTTPException(409, "车内有人，不能解除接运责任；请恢复通道或重新规划到出口。")
        append_event(session, drill, "vehicle.cancelled", identity.username, f"{vehicle['name']}已取消行程并原地待命。", {"vehicle_id": vehicle["id"], "mission_id": vehicle["mission_id"]})
    else:
        plan = protect_plan(plan_vehicle(state["road_network"], vehicle, vehicle["target_node_id"]), state, vehicle["id"])
        append_event(session, drill, "vehicle.replanned", identity.username, f"{vehicle['name']}重新规划当前行程。", {**plan, "vehicle_id": vehicle["id"], "mission_id": vehicle["mission_id"]})
    record_vehicle_arrivals(session, drill)
    commit_changes(session)
    return snapshot(session, drill)


def robot_runtime(robot: RobotAgent | None, events: list[DrillEvent], elapsed: int, replay: bool = False) -> dict | None:
    if robot is None:
        return None
    targets = [event for event in events if event.event_type == "robot.target_assigned"]
    replans = {event.payload.get("target_event_id"): event for event in events if event.event_type == "robot.replanned"}
    cancelled = {event.payload.get("target_event_id"): event for event in events if event.event_type == "robot.task_cancelled"}
    x, y, cursor, queue = (18, 53, 0, []) if replay else (robot.x, robot.y, 0, [])
    world = next((e.payload.get("world") for e in events if e.event_type == "drill.created"), None)
    if replay and world:
        x, y = world["robot_origin"]["x"], world["robot_origin"]["y"]
    position_at = -1
    route, active_label = robot.route, robot.current_task
    if replay:
        route, active_label = [], None
    for event in targets:
        if event.id in cancelled:
            cancel = cancelled[event.id]
            cursor = max(cursor, cancel.elapsed_seconds)
            if cancel.elapsed_seconds >= position_at:
                x, y = cancel.payload.get("x", x), cancel.payload.get("y", y)
                position_at = cancel.elapsed_seconds
            queue.append({"id": event.id, "label": event.payload.get("target") or event.message, "status": "cancelled", "progress": 0, "route_points": [], "route_edge_ids": [], "planned_duration_seconds": 0, "starts_at_seconds": cursor, "ends_at_seconds": cursor})
            continue
        plan = replans.get(event.id, event)
        points = plan.payload.get("route_points", [])
        reachable = len(points) > 1
        duration = max(8, plan.payload.get("planned_duration_seconds", (len(points) - 1) * 4))
        start_at = max(cursor, plan.elapsed_seconds)
        end_at = start_at + (duration if reachable else 1_000_000_000)
        progress = max(0.0, min(1.0, (elapsed - start_at) / duration)) if reachable else 0.0
        task_status = "queued" if elapsed < start_at else "blocked" if not reachable else "completed" if elapsed >= end_at else "executing"
        queue.append({"id": event.id, "label": event.payload.get("target") or event.message, "status": task_status, "progress": round(progress, 3), "route_points": points, "route_edge_ids": plan.payload.get("route_edge_ids", []), "planned_duration_seconds": duration, "starts_at_seconds": start_at, "ends_at_seconds": end_at})
        if points and task_status != "queued":
            x, y = route_position(points, progress)
            position_at = min(elapsed, end_at)
            route, active_label = plan.payload.get("route", []), event.payload.get("target")
        cursor = end_at
    pending = [item for item in queue if item["status"] in {"executing", "queued", "blocked"}]
    if any(item["status"] == "blocked" for item in pending):
        state, reason = "blocked", "目标不可达；请取消当前任务或调整道路后重新规划。"
    elif pending:
        state, reason = "executing", "沿真实道路逐段移动；后续目标按队列顺序执行。"
    elif any(item["status"] == "completed" for item in queue):
        last_motion = max((event.sequence for event in events if event.event_type in {"robot.target_assigned", "robot.replanned"}), default=0)
        last_broadcast = max((event.sequence for event in events if event.event_type == "robot.broadcast_completed"), default=0)
        state = "completed" if last_broadcast > last_motion else "arrived"
        reason = "目标点广播已完成" if state == "completed" else "已到达目标点，可以执行现场广播。"
    else:
        state, reason = ("idle", "任务已取消，等待新目标") if cancelled else ("idle", "等待目标指派") if replay else (robot.state, robot.reason)
    battery = next((e.payload["battery"] for e in reversed(events) if "battery" in e.payload), 96) if replay else robot.battery
    return {"id": robot.id, "name": robot.name, "state": state, "battery": battery, "x": round(x, 2), "y": round(y, 2), "current_task": active_label, "route": route, "reason": reason, "task_queue": queue}


def robot_target(event: DrillEvent) -> tuple[float, float]:
    # Earlier demo runs only recorded route_points; retain their original destination.
    last = (event.payload.get("route_points") or [{"x": 58, "y": 54}])[-1]
    return event.payload.get("target_x", last["x"]), event.payload.get("target_y", last["y"])


def replan_robot_queue(session: Session, drill: DrillSession, robot: RobotAgent, reason: str) -> None:
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    live = robot_runtime(robot, events, effective_elapsed(drill))
    pending = [item for item in live["task_queue"] if item["status"] in {"executing", "queued", "blocked"}]
    robot.x, robot.y = live["x"], live["y"]
    start = (robot.x, robot.y)
    for item in pending:
        target_event = session.get(DrillEvent, item["id"])
        target = robot_target(target_event)
        route, points, edge_ids, distance, risks = plan_robot_route(session, drill, start, target)
        append_event(session, drill, "robot.replanned", robot.name, reason if len(points) > 1 else "封锁后目标不可达，机器人停止并等待重新指派。", {"target_event_id": target_event.id, "target": item["label"], "target_x": target[0], "target_y": target[1], "x": start[0], "y": start[1], "route": route, "route_points": points, "route_edge_ids": edge_ids, "route_distance": distance, "route_risks": risks, "planned_duration_seconds": max(8, round(distance / 3.5))})
        start = target
    robot.reason = reason


def snapshot(session: Session, drill: DrillSession) -> dict:
    all_events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    events = list(reversed(all_events[-160:]))
    robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    tasks = list(session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id == drill.scene_version_id).order_by(DecisionTask.created_at.desc())))
    score = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
    completed_task_ids = {event.payload.get("task_id") for event in all_events if event.event_type == "task.completed"}
    elapsed = effective_elapsed(drill)
    live_robot = robot_runtime(robot, all_events, elapsed)
    participant_events = [event for event in all_events if event.event_type.startswith("participant.") and event.event_type != "participant.joined"]
    participant_sessions = list(session.scalars(select(ParticipantSession).where(
        ParticipantSession.drill_session_id == drill.id,
        ParticipantSession.left_at.is_(None),
    ).order_by(ParticipantSession.joined_at)))
    online_cutoff = datetime.now(UTC) - timedelta(seconds=PARTICIPANT_ONLINE_SECONDS)
    participant_state = []
    action_labels = {"acknowledge": "已确认警报", "arrived": "已到达岗位", "resource_ready": "资源已就绪", "resident_counted": "已完成清点"}
    for participant in drill.participants:
        role_events = [event for event in participant_events if event.actor == participant.get("role")]
        latest = role_events[-1] if role_events else None
        action = latest.event_type.removeprefix("participant.") if latest else None
        role_sessions = [item for item in participant_sessions if item.role == participant.get("role")]
        members = [{
            "id": item.id,
            "name": item.display_name,
            "online": aware(item.last_seen_at) >= online_cutoff,
            "last_seen_at": aware(item.last_seen_at).isoformat(),
        } for item in role_sessions]
        online_count = sum(1 for item in members if item["online"])
        if participant.get("role") == "演练总控/导演":
            online_count = 1
            members = [{"id": "director", "name": "演练总控", "online": True, "last_seen_at": datetime.now(UTC).isoformat()}]
        status_text = f"{online_count} 人在线" if online_count else action_labels.get(action, "等待设备上线" if drill.status == "running" else "当前离线")
        participant_state.append({
            **participant, "connected": online_count > 0, "online_count": online_count,
            "registered_count": len(role_sessions) if role_sessions else (1 if participant.get("role") == "演练总控/导演" else 0),
            "members": members, "status": status_text, "last_action": action,
            "last_message": latest.message if latest else None,
            "last_seen_seconds": latest.elapsed_seconds if latest else None, "action_count": len(role_events),
        })
    simulation = simulation_state(drill, all_events, elapsed, session=session)
    world = simulation.get("world")
    task_states = projected_tasks(world, all_events, elapsed, simulation, live_robot) if world else None
    score_preview = calculate_score_data(session, drill, all_events, simulation)
    derived_commands = command_feedback(all_events, simulation, live_robot, elapsed, drill.status)
    return {
        "id": drill.id, "name": drill.name, "status": drill.status, "time_scale": drill.time_scale,
        "elapsed_seconds": elapsed, "participants": participant_state,
        "events": [{"id": e.id, "sequence": e.sequence, "event_type": e.event_type, "actor": e.actor, "message": e.message, "elapsed_seconds": e.elapsed_seconds, "payload": {k: v for k, v in e.payload.items() if k not in {"world", "token_hash", "participant_token"}}} for e in events],
        "robot": live_robot,
        "tasks": task_states if task_states is not None else [{"id": t.id, "title": t.title, "target": t.target, "deadline_seconds": t.deadline_seconds, "status": "completed" if t.id in completed_task_ids else "pending"} for t in tasks],
        "engine_version": world.get("schema_version", 2) if world else 1,
        "branch": next((e.payload for e in all_events if e.event_type == "drill.branched"), None),
        "director_enabled": next((e.payload.get("enabled", False) for e in reversed(all_events) if e.event_type == "director.configured"), False),
        "score": None if score is None else {"total_score": score.total_score, "details": score.details, "recommendations": score.recommendations},
        "score_preview": score_preview,
        "simulation": simulation,
        "latest_event_sequence": all_events[-1].sequence if all_events else 0,
        "state_version": state_version(all_events[-1].sequence if all_events else 0, elapsed, participant_presence_revision(session, drill.id)),
        "commands": ledger_feedback(session, drill, derived_commands),
    }


@router.post("/scenes/{scene_id}/drills", status_code=status.HTTP_201_CREATED)
@serialized_command
def create_drill(scene_id: str, payload: DrillCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到该场景。")
    owned_community(session, scene.community_id, identity.username)
    if scene.status != SceneStatus.PUBLISHED:
        raise HTTPException(status_code=422, detail="只有已发布场景才能创建演练场次。")
    from app.services.scene_validation import validate_configuration
    validation = validate_configuration(session, scene)
    if not validation['passed']:
        raise HTTPException(422, '场景配置已失效，请返回场景准备修复：' + '；'.join(validation['issues']))
    version = scene.versions[-1]
    drill = DrillSession(scene_id=scene.id, scene_version_id=version.id, name=payload.name, time_scale=payload.time_scale, participants=PARTICIPANTS, status="ready")
    session.add(drill); session.flush()
    world = capture_world(session, version)
    session.add(RobotAgent(drill_session_id=drill.id, x=world["robot_origin"]["x"], y=world["robot_origin"]["y"], route=[]))
    append_event(session, drill, "drill.created", "系统", "场次已创建，地图、人口与任务已冻结。", {"world": world})
    commit_changes(session)
    return snapshot(session, drill)


@router.get("/scenes/{scene_id}/drills")
def list_drills(scene_id: str, summary: bool = False, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到该场景。")
    owned_community(session, scene.community_id, identity.username)
    drills = list(session.scalars(select(DrillSession).where(DrillSession.scene_id == scene_id).order_by(DrillSession.created_at.desc())))
    if summary:
        result = []
        for drill in drills:
            score = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
            world = frozen_world(session, drill)
            result.append({
                "id": drill.id, "name": drill.name, "status": drill.status,
                "created_at": drill.created_at.isoformat(), "elapsed_seconds": effective_elapsed(drill),
                "resident_count": len(world["residents"]) if world else None,
                "score": None if score is None else {"total_score": score.total_score, "details": score.details, "recommendations": score.recommendations},
            })
        return result
    return [snapshot(session, drill) for drill in drills]


@router.get("/drills/{drill_id}")
def get_drill(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    # Opening a view must not queue behind an unrelated engine write transaction.
    # Only the scheduler and explicit commands reconcile execution milestones.
    return snapshot(session, drill)


@router.patch("/drills/{drill_id}/state")
@serialized_command
def change_state(drill_id: str, payload: DrillAction, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    allowed = {"start": {"ready"}, "pause": {"running"}, "resume": {"paused"}, "end": {"running", "paused"}}
    if drill.status not in allowed[payload.action]:
        raise HTTPException(status_code=409, detail=f"当前状态不能执行 {payload.action}。")
    if payload.action in {"pause", "end"}:
        drill.elapsed_seconds = effective_elapsed(drill); drill.started_at = None
    if payload.action in {"start", "resume"}:
        drill.started_at = datetime.now(UTC)
    drill.status = {"start": "running", "pause": "paused", "resume": "running", "end": "ended"}[payload.action]
    if payload.action == "end":
        drill.ended_at = datetime.now(UTC)
    event_names = {"start": "drill.started", "pause": "drill.paused", "resume": "drill.resumed", "end": "drill.ended"}
    append_event(session, drill, event_names[payload.action], "演练总控/导演", {"start": "演练统一时钟已启动。", "pause": "演练已暂停。", "resume": "演练已继续。", "end": "演练已结束并冻结事件。"}[payload.action])
    if payload.action == "end":
        session.flush()
        score_drill(session, drill)
    commit_changes(session)
    return snapshot(session, drill)


@router.post("/drills/{drill_id}/inject")
@serialized_command
def inject_event(drill_id: str, payload: EventInject, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以注入事件。")
    target = payload.target or ""
    valid_target = {
        "channel_blocked": bool(payload.road_edge_id) or any(keyword in target for keyword in ("南门", "通道", "道路")),
        "hydrant_failure": "消火栓" in target,
        "resident_missing": any(keyword in target for keyword in ("居民", "人员", "3 号楼")),
    }[payload.event_type]
    if not valid_target:
        raise HTTPException(status_code=422, detail="事件投放位置与事件类型不匹配，请将事件放到对应道路、消火栓或居民对象。")
    messages = {"channel_blocked": "南门消防通道被车辆占用。", "hydrant_failure": "东侧消火栓压力异常，判定不可用。", "resident_missing": "集合点核验发现 1 名重点人员未签到。"}
    location_payload = {key: value for key, value in {"x": payload.x, "y": payload.y, "target": payload.target}.items() if value is not None}
    if payload.event_type == "resident_missing":
        people = snapshot(session, drill)["simulation"]["residents"]
        person = next((p for p in people if p["id"] == payload.resident_id), None) if payload.resident_id else next((p for p in people if p["status"] != "evacuated" and p["vulnerable"]), None)
        if not person or person["status"] == "evacuated":
            raise HTTPException(422, "请选择尚未到达集合点的具体居民。")
        location_payload["resident_id"] = person["id"]
        messages["resident_missing"] = person["label"]+"失联，最后位置："+person.get("last_location", "社区道路")
    if payload.event_type == "channel_blocked":
        if payload.road_edge_id:
            edge = road_edge_for_drill(session, drill, payload.road_edge_id)
            edge_distance = 0.0
        elif payload.x is not None and payload.y is not None:
            edge, edge_distance = nearest_road_edge(session, drill, (payload.x, payload.y))
            if edge_distance > 12:
                raise HTTPException(status_code=422, detail="封锁点不在道路路段上，请直接点击三维道路。")
        else:
            raise HTTPException(status_code=422, detail="封锁道路必须指定真实路段或道路坐标。")
        history = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id)))
        network = road_network_state(session, drill, history)
        frozen_edge = next(e for e in network["edges"] if e["id"] == edge.id)
        if frozen_edge["status"] == "blocked":
            raise HTTPException(status_code=409, detail="该路段已封锁，请选择其他路段。")
        location_payload.update({"x": (frozen_edge["start"]["x"] + frozen_edge["end"]["x"]) / 2, "y": (frozen_edge["start"]["y"] + frozen_edge["end"]["y"]) / 2})
        location_payload.update({"blocked_edge_id": edge.id, "blocked_edge_name": edge.name, "edge_distance": round(edge_distance, 2)})
        messages["channel_blocked"] = f"{edge.name}已封锁，触发居民与机器人路径重算。"
    append_event(session, drill, f"inject.{payload.event_type}", "演练总控/导演", messages[payload.event_type], location_payload)
    robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    if robot and payload.event_type == "channel_blocked":
        replan_robot_queue(session, drill, robot, f"{location_payload.get('blocked_edge_name', '道路')}已封锁，所有待执行目标按新路网重新规划。")
    if payload.event_type == "channel_blocked":
        replan_vehicle_fleet(session, drill)
    if payload.event_type == "hydrant_failure":
        reconcile_vehicle_services(session, drill)
    commit_changes(session)
    return snapshot(session, drill)


@router.get("/drills/{drill_id}/roads/{edge_id}/preview-block")
def preview_road_block(drill_id: str, edge_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以预演道路封锁。")
    edge = road_edge_for_drill(session, drill, edge_id)
    history = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    network = road_network_state(session, drill, history)
    frozen_edge = next((item for item in network["edges"] if item["id"] == edge.id), None)
    if frozen_edge is None:
        raise HTTPException(status_code=404, detail="当前冻结路网中不存在该路段。")
    if frozen_edge["status"] == "blocked":
        raise HTTPException(status_code=409, detail="该路段已封锁，请选择其他路段。")
    elapsed = effective_elapsed(drill)
    expected_sequence = max((event.sequence for event in history), default=0)
    forecast_at = elapsed + 30
    baseline = simulation_state(drill, history, forecast_at, session=session)
    hypothetical = SimpleNamespace(
        id="preview-road-block", sequence=expected_sequence + 1,
        actor="演练总控/导演",
        elapsed_seconds=elapsed,
        event_type="inject.channel_blocked",
        payload={"blocked_edge_id": edge.id, "blocked_edge_name": edge.name},
    )
    after = simulation_state(drill, [*history, hypothetical], forecast_at, session=session)
    score_before = calculate_score_data(session, drill, history, baseline)["total_score"]
    score_after = calculate_score_data(session, drill, [*history, hypothetical], after)["total_score"]
    affected_residents = [resident for resident in baseline["residents"] if edge.id in resident.get("route_edge_ids", []) and resident["status"] != "evacuated"]
    live_robot = snapshot(session, drill).get("robot") or {}
    affected_robot_tasks = [task for task in live_robot.get("task_queue", []) if edge.id in task.get("route_edge_ids", []) and task.get("status") in {"executing", "queued"}]
    return {
        "kind": "road", "can_apply": True, "title": edge.name, "expected_sequence": expected_sequence,
        "context": {"x": (frozen_edge["start"]["x"] + frozen_edge["end"]["x"]) / 2, "y": (frozen_edge["start"]["y"] + frozen_edge["end"]["y"]) / 2, "target": edge.name, "road_edge_id": edge.id},
        "route_edge_ids": [edge.id], "width_meters": frozen_edge["width_meters"], "risk_score": frozen_edge["risk_score"],
        "affected_residents": len(affected_residents), "affected_robot_tasks": len(affected_robot_tasks),
        "impact": {"congested_before": baseline["summary"]["congested"], "congested_after": after["summary"]["congested"], "smoke_exposed_before": baseline["summary"]["smoke_exposed"], "smoke_exposed_after": after["summary"]["smoke_exposed"], "forecast_horizon_seconds": 30},
        "score_impact": {"before": score_before, "after": score_after, "delta": score_after - score_before, "note": "按当前状态向后推演 30 秒；现场继续变化时将重新校验。"},
        "notice": "预演不会改变现场；确认后写入封路证据，并重算居民与机器人路线。",
    }


@router.post("/drills/{drill_id}/robot/preview")
def preview_robot_target(drill_id: str, payload: RobotCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以规划机器人任务。")
    if payload.command != "move" or payload.x is None or payload.y is None:
        raise HTTPException(status_code=422, detail="机器人预演必须提供空间目标。")
    robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    if robot is None:
        raise HTTPException(status_code=404, detail="未找到机器人。")
    state = snapshot(session, drill)
    live = state["robot"]
    pending = [item for item in live.get("task_queue", []) if item["status"] in {"executing", "queued"}]
    start = (live["x"], live["y"])
    if pending:
        last_target = session.get(DrillEvent, pending[-1]["id"])
        start = robot_target(last_target)
    route, points, edge_ids, distance, risks = plan_robot_route(session, drill, start, (payload.x, payload.y))
    reachable = len(points) >= 2 and "目标不可达" not in route
    return {
        "kind": "robot", "can_apply": reachable, "title": payload.target or "空间目标处置", "expected_sequence": state["latest_event_sequence"],
        "context": {"x": payload.x, "y": payload.y, "target": payload.target or "空间目标处置"},
        "route_points": points, "route_edge_ids": edge_ids, "route_distance": distance,
        "planned_duration_seconds": max(8, round(distance / 3.5)) if reachable else None,
        "queue_position": len(pending) + 1, "risk_score": round(sum(item["cost"] for item in risks) / max(1, len(risks)), 1),
        "risk_details": risks, "notice": "A* 按封锁、道路宽度、实时通行密度、入口排队与当前烟气风险计算；确认前不会写入任务队列。",
        "score_impact": {"before": state["score_preview"]["total_score"], "after": state["score_preview"]["total_score"], "delta": 0, "note": "加入队列本身不计分；机器人到达并完成现场动作后才形成得分证据。"},
    }


@router.post("/drills/{drill_id}/robot")
@serialized_command
def command_robot(drill_id: str, payload: RobotCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以驱动机器人执行任务。")
    robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    if robot is None:
        raise HTTPException(status_code=404, detail="未找到机器人。")
    if payload.command == "move":
        if payload.x is None or payload.y is None:
            raise HTTPException(status_code=422, detail="空间目标必须包含坐标。")
        current_robot = snapshot(session, drill)["robot"]
        pending = [item for item in current_robot.get("task_queue", []) if item["status"] in {"executing", "queued"}]
        if pending:
            last_target = session.get(DrillEvent, pending[-1]["id"])
            robot.x, robot.y = robot_target(last_target)
        else:
            robot.x, robot.y = current_robot["x"], current_robot["y"]
        route, route_points, route_edge_ids, route_distance, route_risks = plan_robot_route(session, drill, (robot.x, robot.y), (payload.x, payload.y))
        if len(route_points) < 2 or "目标不可达" in route:
            raise HTTPException(status_code=409, detail="目标在当前道路封锁条件下不可达，请调整目标或解除封锁。")
        robot.state = "executing"; robot.route = route; robot.current_task = current_robot.get("current_task") if pending else payload.target or "空间目标处置"
        robot.battery = max(0, robot.battery - max(1, round(route_distance / 18)))
        robot.reason = f"A* 风险路径已生成，共 {max(0, len(route_points) - 1)} 段"
        event_type, message = "robot.target_assigned", f"机器人已接受目标：{payload.target or '空间目标处置'}（队列第 {len(pending) + 1} 项）"
        event_payload = {"state": robot.state, "x": robot.x, "y": robot.y, "target_x": payload.x, "target_y": payload.y, "target": payload.target or "空间目标处置", "task_id": payload.task_id, "route": route, "route_points": route_points, "route_edge_ids": route_edge_ids, "route_distance": route_distance, "route_risks": route_risks, "planned_duration_seconds": max(8, round(route_distance / 3.5)), "queue_position": len(pending) + 1}
    elif payload.command == "replan":
        replan_robot_queue(session, drill, robot, "依据当前道路封锁、宽度与烟气风险重新规划任务队列。")
        commit_changes(session)
        return snapshot(session, drill)
    elif payload.command == "cancel":
        live = snapshot(session, drill)["robot"]
        item = next((item for item in live["task_queue"] if item["id"] == payload.task_id and item["status"] in {"queued", "executing", "blocked"}), None)
        if item is None:
            raise HTTPException(status_code=409, detail="只能取消当前场次中尚未完成的机器人任务。")
        append_event(session, drill, "robot.task_cancelled", identity.username, f"已取消任务：{item['label']}", {"target_event_id": item["id"], "x": live["x"], "y": live["y"]})
        robot.x, robot.y = live["x"], live["y"]
        replan_robot_queue(session, drill, robot, "取消任务后从当前位置衔接后续队列。")
        commit_changes(session)
        return snapshot(session, drill)
    elif payload.command == "broadcast":
        current_robot = snapshot(session, drill)["robot"]
        if current_robot["state"] == "completed":
            return snapshot(session, drill)
        if current_robot["state"] not in {"arrived", "completed"}:
            progress = next((item["progress"] for item in current_robot.get("task_queue", []) if item["status"] == "executing"), 0)
            raise HTTPException(status_code=409, detail=f"机器人尚未到达任务点（{round(progress * 100)}%），不能提前完成现场广播。")
        robot.state = "completed"; robot.current_task = current_robot.get("current_task") or "目标点疏散广播"; robot.x, robot.y = current_robot["x"], current_robot["y"]; robot.battery = max(0, robot.battery - 3); robot.reason = "已在目标点完成现场广播，任务形成闭环证据"
        event_type, message = "robot.broadcast_completed", robot.reason
        event_payload = {"state": robot.state, "x": robot.x, "y": robot.y, "target": robot.current_task}
    else:
        live = snapshot(session, drill)["robot"]
        if not live["task_queue"] or all(item["status"] == "cancelled" for item in live["task_queue"]):
            return command_robot(drill_id, RobotCommand(command="move", x=58, y=54, target="3 号楼入口疏散广播"), identity, session)
        event_type, message = "robot.telemetry", f"机器人实况：{live['state']}，位置 ({live['x']}, {live['y']})"
        event_payload = {"state": live["state"], "x": live["x"], "y": live["y"]}
    event_payload["battery"] = robot.battery
    append_event(session, drill, event_type, robot.name, message, event_payload)
    commit_changes(session)
    return snapshot(session, drill)


@router.post("/drills/{drill_id}/residents")
@serialized_command
def command_residents(drill_id: str, payload: ResidentCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以指挥居民。")
    world = frozen_world(session, drill)
    valid_ids = {p["id"] for p in world["residents"]} if world else {f"resident-{index}" for index in range(1, 19)}
    if not set(payload.resident_ids).issubset(valid_ids):
        raise HTTPException(status_code=422, detail="包含无效居民编号。")
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    exit_name = "北门" if payload.exit == "north" else "南门"
    action_name = "重点护送" if payload.action == "priority_assist" else "分流疏散"
    before = simulation_state(drill, events, session=session)
    if world and payload.action == "priority_assist":
        selected = [p for p in before["residents"] if p["id"] in payload.resident_ids and p["status"] != "evacuated"]
        if any(not p["vulnerable"] for p in selected):
            raise HTTPException(422, "重点护送仅用于重点人员；普通居民请使用分流疏散。")
        active = {h["resident_id"] for h in before["helpers"] if h["state"] != "completed"}
        if len(active | {p["id"] for p in selected}) > 4:
            raise HTTPException(409, "本场仅配置 4 名护送员，请等待在途护送完成。")
    if all(resident["status"] == "evacuated" for resident in before["residents"] if resident["id"] in payload.resident_ids):
        raise HTTPException(status_code=409, detail="所选居民已全部到达安全出口，无需重复下达疏散指令。")
    exits = [n for n in before["road_network"]["nodes"] if n["is_exit"]]
    target_node = (min(exits, key=lambda n: n["y"]) if payload.exit == "north" else max(exits, key=lambda n: n["y"])) if exits else None
    target = (target_node["x"], target_node["y"]) if target_node else (12.0, 12.0) if payload.exit == "north" else (84.0, 88.0)
    spatial = spatial_preview(session, drill, payload, events) if world and world.get("schema_version", 2) >= 3 else None
    for resident in before["residents"]:
        if resident["id"] in payload.resident_ids and resident["status"] != "evacuated":
            if spatial:
                points = next(p["route_points"] if p["route_reachable"] else [] for p in spatial["residents"] if p["id"] == resident["id"])
            else:
                _, points, _, _, _ = plan_route(before["road_network"], (resident["x"], resident["y"]), target, effective_elapsed(drill))
            if len(points) < 2:
                raise HTTPException(status_code=409, detail=f"{resident['label']} 无法沿当前道路到达{exit_name}，请选择另一出口。")
    command_event = append_event(session, drill, "resident.command", "应急指挥人员", f"已指挥 {len(payload.resident_ids)} 名居民向{exit_name}{action_name}。", payload.model_dump())
    forecast_at = effective_elapsed(drill) + 30
    baseline = simulation_state(drill, events, forecast_at, session=session)
    after = simulation_state(drill, [*events, command_event], forecast_at, session=session)
    command_event.payload = {
        **command_event.payload,
        "impact": {
            "congested_before": baseline["summary"]["congested"], "congested_after": after["summary"]["congested"],
            "smoke_exposed_before": baseline["summary"]["smoke_exposed"], "smoke_exposed_after": after["summary"]["smoke_exposed"],
            "forecast_horizon_seconds": 30,
            "selected_count": len(payload.resident_ids),
        },
    }
    commit_changes(session)
    return snapshot(session, drill)


def spatial_preview(session, drill, payload, events=None):
    events = events if events is not None else list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    elapsed = effective_elapsed(drill)
    command = SimpleNamespace(sequence=max((e.sequence for e in events), default=0)+1, elapsed_seconds=elapsed, event_type="resident.command", payload=payload.model_dump())
    return simulation_state(drill, [*events, command], elapsed, session=session)


@router.post("/drills/{drill_id}/residents/preview")
def preview_resident_route(drill_id: str, payload: ResidentCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    world = frozen_world(session, drill)
    if not world or world.get("schema_version", 2) < 3:
        raise HTTPException(409, "请新建连续空间版本的训练。")
    if not set(payload.resident_ids).issubset({p["id"] for p in world["residents"]}):
        raise HTTPException(422, "包含无效居民编号。")
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    data = spatial_preview(session, drill, payload, events)
    selected = [p for p in data["residents"] if p["id"] in payload.resident_ids]
    elapsed = effective_elapsed(drill)
    forecast_at = elapsed + 30
    baseline = simulation_state(drill, events, forecast_at, session=session)
    expected_sequence = max((event.sequence for event in events), default=0)
    command = SimpleNamespace(id="preview-resident-command", sequence=expected_sequence + 1, elapsed_seconds=elapsed, actor="应急指挥人员", event_type="resident.command", payload=payload.model_dump())
    after = simulation_state(drill, [*events, command], forecast_at, session=session)
    score_before = calculate_score_data(session, drill, events, baseline)["total_score"]
    score_after = calculate_score_data(session, drill, [*events, command], after)["total_score"]
    reachable = [person for person in selected if person["route_reachable"] and person["status"] != "evacuated"]
    return {
        "kind": "residents", "at_seconds": elapsed, "exit": payload.exit, "action": payload.action, "expected_sequence": expected_sequence,
        "residents": selected, "can_apply": len(reachable) == len(selected),
        "route_edge_ids": sorted({edge_id for person in selected for edge_id in person.get("route_edge_ids", [])}),
        "planned_duration_seconds": round(max((person.get("remaining_seconds", 0) for person in reachable), default=0)),
        "impact": {"congested_before": baseline["summary"]["congested"], "congested_after": after["summary"]["congested"], "smoke_exposed_before": baseline["summary"]["smoke_exposed"], "smoke_exposed_after": after["summary"]["smoke_exposed"], "forecast_horizon_seconds": 30},
        "score_impact": {"before": score_before, "after": score_after, "delta": score_after - score_before, "note": "按当前队列和烟气状态向后推演 30 秒，不把下达指令直接当作人员到达。"},
        "notice": "预演不改变现场；确认时重新校验实时路况。预计时间包含当前楼内通行，但后续新扰动会改变结果。",
    }


@router.post("/drills/{drill_id}/searches")
@serialized_command
def assign_search(drill_id: str, payload: SearchAssignment, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    state = snapshot(session, drill)
    if drill.status != "running" or state["engine_version"] < 3:
        raise HTTPException(409, "只有运行中的连续空间训练可以派出搜索员。")
    person = next((p for p in state["simulation"]["residents"] if p["id"] == payload.resident_id), None)
    if not person or person["status"] == "evacuated":
        raise HTTPException(422, "请选择未到集合点的居民。")
    active = [h for h in state["simulation"]["helpers"] if h["state"] != "completed"]
    if any(h["resident_id"] == person["id"] for h in active) or len(active) >= 4:
        raise HTTPException(409, "此人已有搜索/护送责任人，或 4 名接应人员均在执行任务。")
    append_event(session, drill, "resident.search_assigned", identity.username, f"{payload.responsible}负责寻找{person['label']}，最后位置：{person['last_location']}", {**payload.model_dump(), "last_location": person["last_location"]})
    commit_changes(session)
    return snapshot(session, drill)


@router.post("/drills/{drill_id}/branches", status_code=201)
@serialized_command
def create_editable_branch(drill_id: str, payload: EditableBranchCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    source = require_drill(session, drill_id, identity.username)
    if payload.at_seconds > effective_elapsed(source):
        raise HTTPException(422, "分支起点不能晚于已发生时间。")
    world = frozen_world(session, source)
    if not world or world.get("schema_version", 2) < 3:
        raise HTTPException(409, "旧版训练保持只读回放，请新建连续空间训练后重做。")
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == source.id).order_by(DrillEvent.sequence)))
    if payload.before_sequence is not None:
        chosen = next((e for e in events if e.sequence == payload.before_sequence), None)
        if not chosen or chosen.event_type == "drill.created" or chosen.elapsed_seconds != payload.at_seconds:
            raise HTTPException(422, "决定序号与分支时刻不一致。")
    prefix = [e for e in events if e.elapsed_seconds <= payload.at_seconds and (payload.before_sequence is None or e.sequence < payload.before_sequence)]
    branch = DrillSession(scene_id=source.scene_id, scene_version_id=source.scene_version_id, name=payload.name, time_scale=source.time_scale, participants=deepcopy(PARTICIPANTS), status="paused", elapsed_seconds=payload.at_seconds)
    session.add(branch); session.flush()
    from app.services.branching import fork_events
    for data in fork_events(prefix, identity.username): session.add(DrillEvent(drill_session_id=branch.id, **data))
    source_robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == source.id))
    robot = robot_runtime(source_robot, prefix, payload.at_seconds, replay=True)
    session.add(RobotAgent(drill_session_id=branch.id, x=robot["x"], y=robot["y"], battery=robot["battery"], route=[]))
    session.flush()
    append_event(session, branch, "drill.branched", identity.username, "从历史时刻创建可操作分支；原场次与后续决定不改变。", {"source_drill_id": source.id, "at_seconds": payload.at_seconds, "before_sequence": payload.before_sequence, "source_name": source.name})
    commit_changes(session)
    return snapshot(session, branch)


@router.get("/drills/{drill_id}/branch-comparison")
def compare_editable_branch(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    branch = require_drill(session, drill_id, identity.username)
    created = session.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == branch.id, DrillEvent.event_type == "drill.branched"))
    if not created: raise HTTPException(409, "当前场次不是历史分支。")
    source = require_drill(session, created.payload["source_drill_id"], identity.username)
    at = min(effective_elapsed(source), effective_elapsed(branch))
    worlds = []
    for drill in (source, branch):
        events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.elapsed_seconds <= at).order_by(DrillEvent.sequence)))
        worlds.append(simulation_state(drill, events, at, session=session))
    originals = {p["id"]: p for p in worlds[0]["residents"]}
    return {"at_seconds": at, "source_name": source.name, "branch_name": branch.name, "worlds": {"baseline": worlds[0], "alternative": worlds[1]}, "residents": [{"id": p["id"], "label": p["label"], "original_status": originals[p["id"]]["behavior"], "branch_status": p["behavior"], "exposure_delta": round(p["smoke_exposure"]-originals[p["id"]]["smoke_exposure"], 2), "queue_delta": round(p["queue_seconds"]-originals[p["id"]]["queue_seconds"], 2)} for p in worlds[1]["residents"]], "notice": "同一批居民、同一已发生时刻比较，不预测原场次未来。负差值表示本次更少。"}


@router.post("/drills/{drill_id}/participant-actions")
@serialized_command
def participant_action(drill_id: str, payload: ParticipantAction, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以提交参演反馈。")
    if payload.role not in {item["role"] for item in drill.participants} - {"演练总控/导演"}:
        raise HTTPException(status_code=422, detail="请选择当前演练配置的参演角色。")
    validate_feedback(session, drill, payload)
    action_labels = {"acknowledge": "确认警报", "arrived": "到达岗位", "resource_ready": "资源就绪", "resident_counted": "居民清点", "report": "异常报告"}
    append_event(session, drill, f"participant.{payload.action}", payload.role, f"{action_labels[payload.action]}：{payload.message}", payload.model_dump(exclude={"participant_token"}))
    commit_changes(session)
    return snapshot(session, drill)


@router.get("/drills/{drill_id}/participant-invite")
def participant_invite(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    try:
        lan_addresses = [address for address in socket.gethostbyname_ex(socket.gethostname())[2] if not address.startswith("127.")]
    except OSError:
        lan_addresses = []
    return {"drill_id": drill.id, "code": participant_code(drill.id), "name": drill.name, "lan_addresses": lan_addresses}


@router.get("/participant/resolve")
def resolve_participant_code(code: str, session: Session = Depends(get_db)):
    normalized = code.strip().upper()
    if not re.fullmatch(r"[0-9A-F]{6}", normalized):
        raise HTTPException(422, "请输入 6 位演练加入码。")
    matches = session.scalars(select(DrillSession).where(
        func.upper(func.substr(DrillSession.id, -6)) == normalized,
        DrillSession.status.in_(["ready", "running", "paused"]),
    ).limit(2)).all()
    if not matches:
        raise HTTPException(404, "加入码无效或演练已结束，请向导演核对。")
    if len(matches) > 1:
        raise HTTPException(409, "该加入码对应多个场次，请使用导演分享的完整参演链接。")
    return {"drill_id": matches[0].id, "code": normalized, "name": matches[0].name}


@router.get("/participant/drills/{drill_id}")
def public_participant_drill(drill_id: str, code: str, session: Session = Depends(get_db)):
    return snapshot(session, require_participant_drill(session, drill_id, code))


@router.post("/participant/drills/{drill_id}/actions")
@serialized_command
def public_participant_action(drill_id: str, code: str, payload: ParticipantAction, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以提交参演反馈。")
    if payload.role not in {item["role"] for item in drill.participants} - {"演练总控/导演"}:
        raise HTTPException(status_code=422, detail="请选择当前演练配置的参演角色。")
    if frozen_world(session, drill):
        member = participant_identity(session, drill, payload.participant_token)
        if member["role"] != payload.role:
            raise HTTPException(403, "不能以其他身份提交反馈。")
    validate_feedback(session, drill, payload)
    action_labels = {"acknowledge": "确认警报", "arrived": "到达岗位", "resource_ready": "资源就绪", "resident_counted": "居民清点", "report": "异常报告"}
    append_event(session, drill, f"participant.{payload.action}", payload.role, f"{action_labels[payload.action]}：{payload.message}", payload.model_dump(exclude={"participant_token"}))
    commit_changes(session)
    return snapshot(session, drill)


@router.patch("/participant/drills/{drill_id}/tasks/{task_id}/complete")
@serialized_command
def public_complete_task(drill_id: str, task_id: str, code: str, session: Session = Depends(get_db)):
    drill = require_participant_drill(session, drill_id, code)
    if frozen_world(session, drill):
        raise HTTPException(409, "新版任务需要接收、到位和证据核验，请使用任务流程。")
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以提交处置任务。")
    task = session.get(DecisionTask, task_id)
    if task is None or task.scene_version_id != drill.scene_version_id:
        raise HTTPException(status_code=404, detail="未找到该场次的处置任务。")
    completion_events = session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "task.completed"))
    if not any(event.payload.get("task_id") == task.id for event in completion_events):
        append_event(session, drill, "task.completed", "手机参演端", f"任务已完成：{task.title}", {"task_id": task.id})
        commit_changes(session)
    return snapshot(session, drill)


@router.post("/drills/{drill_id}/director/advance")
@serialized_command
def advance_director(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="自适应导演仅在演练运行时工作。")
    event_types = {event.event_type for event in session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id))}
    simulation = simulation_state(drill, list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id))), session=session)
    candidates = [
        (simulation["summary"]["congested"] * 6 + (22 if simulation["environment"]["south_lane"] != "blocked" else 0), "inject.channel_blocked", "道路承载接近阈值，导演注入最近道路封锁。", {"x": 50, "y": 88, "target": "南门道路", "decision_basis": "congestion"}),
        (simulation["fire"]["intensity"] + simulation["summary"]["smoke_exposed"] * 5, "inject.hydrant_failure", "火势与烟气负荷上升，导演注入东侧消火栓失效。", {"x": 78, "y": 44, "target": "东侧消火栓", "decision_basis": "fire_and_smoke"}),
        (simulation["summary"]["evacuated"] * 4 + effective_elapsed(drill) / 4, "inject.resident_missing", "疏散已进入清点阶段，导演注入重点居民失联。", {"x": 64, "y": 50, "target": "3 号楼居民", "decision_basis": "evacuation_and_rollcall"}),
    ]
    pending = [candidate for candidate in candidates if candidate[1] not in event_types]
    if pending:
        _, event_type, message, event_payload = max(pending, key=lambda candidate: candidate[0])
        if event_type == "inject.channel_blocked":
            edge, edge_distance = nearest_road_edge(session, drill, (event_payload["x"], event_payload["y"]))
            event_payload.update({"blocked_edge_id": edge.id, "blocked_edge_name": edge.name, "edge_distance": round(edge_distance, 2)})
        append_event(session, drill, event_type, "自适应事件导演", message, event_payload)
        append_event(session, drill, "director.cue", "自适应事件导演", f"镜头已聚焦：{event_payload['target']}，请立即处置。", {**event_payload, "severity": "high"})
        if event_type == "inject.channel_blocked":
            robot = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
            if robot:
                replan_robot_queue(session, drill, robot, "自适应导演封锁道路，任务队列按新路网重新规划。")
            replan_vehicle_fleet(session, drill)
        if event_type == "inject.hydrant_failure":
            reconcile_vehicle_services(session, drill)
        commit_changes(session)
        return snapshot(session, drill)
    append_event(session, drill, "director.cue", "自适应事件导演", "当前关键扰动均已注入，建议切换双世界比较验证决策。", {"severity": "info", "target": "平行推演"})
    commit_changes(session)
    return snapshot(session, drill)


@router.patch("/drills/{drill_id}/tasks/{task_id}/complete")
@serialized_command
def complete_task(drill_id: str, task_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if frozen_world(session, drill):
        raise HTTPException(409, "不能直接标记完成：请按任务步骤提交处置证据。")
    if drill.status != "running":
        raise HTTPException(status_code=409, detail="只有运行中的演练可以提交处置任务。")
    task = session.get(DecisionTask, task_id)
    if task is None or task.scene_version_id != drill.scene_version_id:
        raise HTTPException(status_code=404, detail="未找到该场次的处置任务。")
    completion_events = session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "task.completed"))
    if not any(event.payload.get("task_id") == task.id for event in completion_events):
        append_event(session, drill, "task.completed", "物业/网格员", f"任务已完成：{task.title}", {"task_id": task.id})
        commit_changes(session)
    return snapshot(session, drill)


@router.get("/drills/{drill_id}/replay")
def replay_drill(drill_id: str, at_seconds: int = 0, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    if at_seconds < 0 or at_seconds > max(effective_elapsed(drill), drill.elapsed_seconds):
        raise HTTPException(status_code=422, detail="回放时间超出本次演练范围。")
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.elapsed_seconds <= at_seconds).order_by(DrillEvent.sequence)))
    robot_agent = session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id))
    completed_task_ids = [event.payload.get("task_id") for event in events if event.event_type == "task.completed"]
    simulation = simulation_state(drill, events, at_seconds, session=session)
    replay_robot = robot_runtime(robot_agent, events, at_seconds, replay=True)
    return {
        "at_seconds": at_seconds,
        "event_count": len(events),
        "latest_event": events[-1].message if events else "演练尚未开始",
        "robot": replay_robot,
        "completed_task_ids": completed_task_ids,
        "simulation": simulation,
        "events": [{"id": e.id, "sequence": e.sequence, "event_type": e.event_type, "actor": e.actor, "message": e.message, "elapsed_seconds": e.elapsed_seconds, "payload": {k: v for k, v in e.payload.items() if k not in {"world", "token_hash", "participant_token"}}} for e in reversed(events)],
        "tasks": projected_tasks(simulation["world"], events, at_seconds, simulation, replay_robot) if simulation.get("world") else [],
    }


@router.get("/drills/{drill_id}/report")
def drill_report(drill_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    data = snapshot(session, drill)
    if data["score"] is None:
        raise HTTPException(status_code=409, detail="演练结束后才能生成复盘报告。")
    all_events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    return {
        "title": f"{drill.name}复盘报告", "status": drill.status, "duration_seconds": drill.elapsed_seconds,
        "participants": data["participants"], "score": data["score"], "score_preview": data["score_preview"], "simulation_summary": data["simulation"]["summary"], "evidence": [{"id": event.id, "sequence": event.sequence, "event_type": event.event_type, "actor": event.actor, "message": event.message, "elapsed_seconds": event.elapsed_seconds, "payload": {k: v for k, v in event.payload.items() if k not in {"token_hash", "participant_token"}}} for event in all_events],
        "robot": data["robot"], "tasks": data["tasks"],
    }


@router.post("/drills/{drill_id}/branches/compare")
def compare_branches(drill_id: str, payload: BranchCompareRequest, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = require_drill(session, drill_id, identity.username)
    events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    current_elapsed = effective_elapsed(drill)
    if payload.at_seconds is not None:
        if payload.at_seconds > current_elapsed:
            raise HTTPException(422, "分支起点不能晚于本场已发生的时间。")
        current_elapsed = payload.at_seconds
        events = [event for event in events if event.elapsed_seconds <= current_elapsed]
    projection_seconds = 90
    projected_elapsed = current_elapsed + projection_seconds
    names = {"south_standard": "南门常规疏散", "north_priority": "北门重点人员优先", "dual_exit": "双出口动态分流协同"}

    def world_for(strategy: str) -> tuple[dict, dict]:
        world = simulation_state(drill, events, projected_elapsed, session=session, strategy=strategy, branch_at=current_elapsed)
        residents = world["residents"]
        remaining = [resident["remaining_seconds"] for resident in residents if resident["status"] != "evacuated" and resident["route_reachable"]]
        vulnerable_remaining = [resident["remaining_seconds"] for resident in residents if resident["vulnerable"] and resident["status"] != "evacuated" and resident["route_reachable"]]
        unreachable = sum(not resident.get("route_reachable", True) for resident in residents)
        smoke_exposed = world["summary"]["smoke_exposed"]
        congested = world["summary"]["congested"]
        unresolved = unreachable + world["summary"]["missing"]
        evacuation_seconds = None if unresolved else round(projected_elapsed + max(remaining) if remaining else max((resident.get("evacuated_at_seconds", projected_elapsed) for resident in residents), default=projected_elapsed))
        vulnerable_unresolved = any((not resident["route_reachable"] or resident["status"] == "missing") and resident["vulnerable"] for resident in residents)
        vulnerable_seconds = None if vulnerable_unresolved else round(projected_elapsed + max(vulnerable_remaining) if vulnerable_remaining else max((resident.get("evacuated_at_seconds", projected_elapsed) for resident in residents if resident["vulnerable"]), default=projected_elapsed))
        route_distance = round(sum(sum(math.dist((points[index]["x"], points[index]["y"]), (points[index + 1]["x"], points[index + 1]["y"])) for index in range(len(points) - 1)) for points in [resident["route_points"] for resident in residents]) / max(1, len(residents)), 1)
        score = max(0, min(100, round(100 - smoke_exposed * 3 - congested * 2 - unresolved * 12 - max(0, (evacuation_seconds or projected_elapsed) - projected_elapsed - 45) * .12)))
        outcome = {
            "strategy": strategy, "name": names[strategy], "evacuation_seconds": evacuation_seconds,
            "vulnerable_rescue_seconds": vulnerable_seconds, "smoke_exposed": smoke_exposed,
            "average_resident_route_units": route_distance,
            "projected_score": score, "unreachable": unreachable, "congested": congested,
        }
        world["parallel_strategy"] = strategy
        world["projected_outcome"] = outcome
        return world, outcome

    baseline_world, baseline = world_for(payload.baseline_strategy)
    alternative_world, alternative = world_for(payload.alternative_strategy)
    projected_robot = robot_runtime(session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id)), events, projected_elapsed)
    score_delta = alternative["projected_score"] - baseline["projected_score"]
    recommendation = f"建议采用“{alternative['name']}”：基于同一道路图继续推演，预计综合得分提升 {score_delta} 分。" if score_delta > 0 else f"“{alternative['name']}”未优于“{baseline['name']}”，请调整出口分配或先解除不可达路段。"
    return {
        "at_seconds": projected_elapsed, "projection_seconds": projection_seconds,
        "baseline": baseline, "alternative": alternative,
        "worlds": {"baseline": baseline_world, "alternative": alternative_world},
        "robots": {"baseline": projected_robot, "alternative": projected_robot},
        "improvement": {
            "evacuation_seconds": None if baseline["evacuation_seconds"] is None or alternative["evacuation_seconds"] is None else baseline["evacuation_seconds"] - alternative["evacuation_seconds"],
            "vulnerable_rescue_seconds": None if baseline["vulnerable_rescue_seconds"] is None or alternative["vulnerable_rescue_seconds"] is None else baseline["vulnerable_rescue_seconds"] - alternative["vulnerable_rescue_seconds"],
            "smoke_exposed": baseline["smoke_exposed"] - alternative["smoke_exposed"],
            "score": score_delta,
        },
        "recommendation": recommendation,
        "disclaimer": "两个世界均从当前事件证据和同一社区道路图出发，按确定性规则向前推演 90 秒；结果用于演练比较，不作为真实火场安全决策依据。",
        "source_state": {"elapsed_seconds": current_elapsed, "event_count": len(events), "road_graph_edges": len(baseline_world.get("road_network", {}).get("edges", []))},
    }


@router.get("/scenes/{scene_id}/comparison")
def compare_drills(scene_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到场景。")
    owned_community(session, scene.community_id, identity.username)
    drills = list(session.scalars(select(DrillSession).where(DrillSession.scene_id == scene_id, DrillSession.status == "ended").order_by(DrillSession.ended_at.desc()).limit(5)))
    result = []
    for drill in drills:
        score = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
        result.append({"id": drill.id, "name": drill.name, "elapsed_seconds": drill.elapsed_seconds, "score": score.total_score if score else 0})
    return result


def completed_drill_record(session: Session, drill: DrillSession) -> dict:
    """Build a comparison record from frozen evidence without replaying the whole world."""
    score_row = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
    score = {"total_score": score_row.total_score, "details": score_row.details, "recommendations": score_row.recommendations} if score_row else {"total_score": 0, "details": [], "recommendations": []}
    ended_event = session.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "drill.ended").order_by(DrillEvent.sequence.desc()))
    stored_summary = (ended_event.payload or {}).get("final_summary") if ended_event else None
    task_summary = (ended_event.payload or {}).get("task_summary") if ended_event else None
    parsed_summary: dict[str, int | None] = {"total": None, "evacuated": None, "counted": None, "smoke_exposed": None, "missing": None, "congested": None}
    if stored_summary:
        parsed_summary.update({key: stored_summary.get(key) for key in parsed_summary})
    else:
        for detail in score["details"]:
            evidence = str(detail.get("evidence", ""))
            if match := re.search(r"已到达\s*(\d+)/(\d+).*已核验\s*(\d+)/(\d+)", evidence):
                parsed_summary.update({"evacuated": int(match.group(1)), "total": int(match.group(2)), "counted": int(match.group(3))})
            if match := re.search(r"暴露\s*(\d+)\s*人；失联\s*(\d+)\s*人", evidence):
                parsed_summary.update({"smoke_exposed": int(match.group(1)), "missing": int(match.group(2))})
            if match := re.search(r"smoke_exposed=(\d+),missing=(\d+)", evidence):
                parsed_summary.update({"smoke_exposed": int(match.group(1)), "missing": int(match.group(2))})
    if not task_summary:
        completed = session.scalar(select(func.count(func.distinct(DrillEvent.id))).where(DrillEvent.drill_session_id == drill.id, DrillEvent.event_type == "task.completed")) or 0
        total = session.scalar(select(func.count(DecisionTask.id)).where(DecisionTask.scene_version_id == drill.scene_version_id)) or 0
        task_summary = {"completed": completed, "total": total}
    evidence_count = session.scalar(
        select(func.count(DrillEvent.id)).where(DrillEvent.drill_session_id == drill.id)
    ) or 0
    return {
        "id": drill.id,
        "name": drill.name,
        "ended_at": drill.ended_at.isoformat() if drill.ended_at else None,
        "elapsed_seconds": drill.elapsed_seconds,
        "score": score["total_score"],
        "score_details": score["details"],
        "recommendations": score["recommendations"],
        "summary": {
            "total": parsed_summary["total"],
            "evacuated": parsed_summary["evacuated"],
            "counted": parsed_summary["counted"],
            "smoke_exposed": parsed_summary["smoke_exposed"],
            "missing": parsed_summary["missing"],
            "congested": parsed_summary["congested"],
        },
        "tasks": task_summary,
        "evidence_count": evidence_count,
    }


def completed_drill_index_record(session: Session, drill: DrillSession) -> dict:
    """Return selector metadata without replaying the resident simulation."""
    score = session.scalar(select(DrillScore).where(DrillScore.drill_session_id == drill.id))
    evidence_count = session.scalar(
        select(func.count(DrillEvent.id)).where(DrillEvent.drill_session_id == drill.id)
    ) or 0
    return {
        "id": drill.id,
        "name": drill.name,
        "ended_at": drill.ended_at.isoformat() if drill.ended_at else None,
        "elapsed_seconds": drill.elapsed_seconds,
        "score": score.total_score if score else 0,
        "score_details": score.details if score else [],
        "recommendations": score.recommendations if score else [],
        "summary": {"total": 0, "evacuated": 0, "counted": 0, "smoke_exposed": 0, "missing": 0, "congested": 0},
        "tasks": {"completed": 0, "total": 0},
        "evidence_count": evidence_count,
    }


def comparison_findings(baseline: dict, candidate: dict) -> tuple[list[str], list[str]]:
    improvements: list[str] = []
    regressions: list[str] = []
    score_delta = candidate["score"] - baseline["score"]
    if score_delta > 0:
        improvements.append(f"综合评分提高 {score_delta} 分")
    elif score_delta < 0:
        regressions.append(f"综合评分下降 {abs(score_delta)} 分")
    duration_delta = candidate["elapsed_seconds"] - baseline["elapsed_seconds"]
    if duration_delta < 0:
        improvements.append(f"处置用时缩短 {abs(duration_delta)} 秒")
    elif duration_delta > 0:
        regressions.append(f"处置用时增加 {duration_delta} 秒")
    labels = {"evacuated": "到达集合点", "smoke_exposed": "烟气暴露", "missing": "失联", "congested": "拥堵"}
    for key, label in labels.items():
        if baseline["summary"][key] is None or candidate["summary"][key] is None:
            continue
        delta = candidate["summary"][key] - baseline["summary"][key]
        higher_is_better = key == "evacuated"
        if delta and ((delta > 0) == higher_is_better):
            improvements.append(f"{label}{'增加' if higher_is_better else '减少'} {abs(delta)} 人")
        elif delta:
            regressions.append(f"{label}{'减少' if higher_is_better else '增加'} {abs(delta)} 人")
    return improvements, regressions


@router.get("/scenes/{scene_id}/outcome-comparison")
def compare_completed_drill_outcomes(
    scene_id: str,
    baseline_id: str | None = None,
    candidate_id: str | None = None,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    session: Session = Depends(get_db),
):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到场景。")
    owned_community(session, scene.community_id, identity.username)
    drills = list(session.scalars(
        select(DrillSession)
        .where(DrillSession.scene_id == scene_id, DrillSession.status == "ended")
        .order_by(DrillSession.ended_at.desc())
        .limit(8)
    ))
    records = [completed_drill_index_record(session, drill) for drill in drills]
    if not baseline_id or not candidate_id:
        return {"runs": records, "comparison": None}
    if baseline_id == candidate_id:
        raise HTTPException(status_code=422, detail="基线训练和复演训练不能是同一场次。")
    indexed_drills = {drill.id: drill for drill in drills}
    if baseline_id not in indexed_drills or candidate_id not in indexed_drills:
        raise HTTPException(status_code=404, detail="所选训练不存在、尚未结束，或不属于当前场景。")
    baseline = completed_drill_record(session, indexed_drills[baseline_id])
    candidate = completed_drill_record(session, indexed_drills[candidate_id])
    improvements, regressions = comparison_findings(baseline, candidate)
    score_delta = candidate["score"] - baseline["score"]
    if score_delta > 0 and not regressions:
        verdict = "复演整体优于基线，关键安全指标未出现退步。"
    elif score_delta > 0:
        verdict = "复演总分提高，但仍有退步指标需要复盘。"
    elif score_delta == 0 and not regressions:
        verdict = "两次训练总分持平，处置结果没有出现明显退步。"
    else:
        verdict = "复演尚未形成稳定提升，建议回看退步指标对应的事件证据。"
    def metric_delta(key: str) -> int | None:
        before, after = baseline["summary"][key], candidate["summary"][key]
        return None if before is None or after is None else after - before

    return {
        "runs": records,
        "comparison": {
            "baseline": baseline,
            "candidate": candidate,
            "delta": {
                "score": score_delta,
                "elapsed_seconds": candidate["elapsed_seconds"] - baseline["elapsed_seconds"],
                "evacuated": metric_delta("evacuated"),
                "smoke_exposed": metric_delta("smoke_exposed"),
                "missing": metric_delta("missing"),
                "congested": metric_delta("congested"),
                "tasks_completed": candidate["tasks"]["completed"] - baseline["tasks"]["completed"],
            },
            "verdict": verdict,
            "improvements": improvements,
            "regressions": regressions,
            "disclaimer": "对比来自两次已结束训练的最终快照与事件证据，仅用于演练复盘，不代表真实火场因果结论。",
        },
    }


@router.post("/communities/{community_id}/demo-reset")
@serialized_command
def reset_demo_drills(community_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    """Clear generated drill runs while preserving the reusable map and published scenes."""
    owned_community(session, community_id, identity.username)
    scene_ids = list(session.scalars(select(Scene.id).where(Scene.community_id == community_id)))
    drill_ids = list(session.scalars(select(DrillSession.id).where(DrillSession.scene_id.in_(scene_ids)))) if scene_ids else []
    if drill_ids:
        session.execute(delete(DrillScore).where(DrillScore.drill_session_id.in_(drill_ids)))
        session.execute(delete(DrillCommand).where(DrillCommand.drill_session_id.in_(drill_ids)))
        session.execute(delete(DrillStateSnapshot).where(DrillStateSnapshot.drill_session_id.in_(drill_ids)))
        session.execute(delete(DrillEngineLease).where(DrillEngineLease.drill_session_id.in_(drill_ids)))
        session.execute(delete(DrillEvent).where(DrillEvent.drill_session_id.in_(drill_ids)))
        session.execute(delete(RobotAgent).where(RobotAgent.drill_session_id.in_(drill_ids)))
        session.execute(delete(DrillSession).where(DrillSession.id.in_(drill_ids)))
    commit_changes(session)
    return {"reset": True, "removed_drills": len(drill_ids), "preserved_scenes": len(scene_ids)}


def _persist_failed_command(
    session: Session,
    drill: DrillSession,
    payload: LiveCommand,
    actor: str,
    failure_code: str,
    reason: str,
) -> None:
    """Persist expected validation failures separately from the rolled-back domain transaction."""
    current = session.get(DrillSession, drill.id)
    if current is None:
        return
    existing = session.scalar(select(DrillCommand).where(
        DrillCommand.drill_session_id == current.id,
        DrillCommand.command_id == payload.command_id,
    ))
    if existing:
        return
    clean_reason = " ".join(str(reason).split())[:500]
    failed_event = append_event(
        session,
        current,
        "command.failed",
        actor,
        f"指令未执行：{clean_reason}",
        {
            "command_id": payload.command_id,
            "kind": payload.kind,
            "target_id": payload.target_id,
            "failure_code": failure_code,
        },
    )
    session.add(DrillCommand(
        drill_session_id=current.id,
        command_id=payload.command_id,
        actor=actor,
        kind=payload.kind,
        target_id=payload.target_id,
        command_args=safe_arguments(payload.arguments),
        expected_sequence=payload.expected_sequence,
        status="failed",
        label="指令未执行",
        reason=clean_reason,
        progress=0,
        submitted_at_seconds=effective_elapsed(current),
        completed_at_seconds=effective_elapsed(current),
        event_ids=[failed_event.id],
        failure_code=failure_code,
    ))
    session.flush()
    persist_snapshot(session, current, snapshot(session, current), force=True)
    session.commit()


@router.post("/drills/{drill_id}/commands")
@serialized_command
def execute_live_command(drill_id: str, payload: LiveCommand, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    """Execute once, persist the lifecycle, and keep domain effects transactionally atomic."""
    from pydantic import ValidationError

    drill = require_drill(session, drill_id, identity.username)
    session.execute(select(DrillSession.id).where(DrillSession.id == drill_id).with_for_update())
    command_record = session.scalar(select(DrillCommand).where(
        DrillCommand.drill_session_id == drill_id,
        DrillCommand.command_id == payload.command_id,
    ))
    if command_record:
        if command_record.actor != identity.username or not same_command(command_record, payload.kind, payload.arguments, payload.target_id):
            raise HTTPException(409, "该指令编号已用于另一项操作，请重新提交。")
        if command_record.status == "failed":
            raise HTTPException(409, f"该指令此前未执行：{command_record.reason} 请重新预览并下达新指令。")
        return snapshot(session, drill)
    receipts = session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill_id, DrillEvent.event_type == "command.accepted"))
    prior = next((e for e in receipts if e.payload.get("command_id") == payload.command_id), None)
    fingerprint = {"kind": payload.kind, "arguments": safe_arguments(payload.arguments), "target_id": payload.target_id}
    if prior:
        if prior.actor != identity.username or any(prior.payload.get(k) != v for k, v in fingerprint.items()):
            raise HTTPException(409, "该指令编号已用于另一项操作，请重新提交。")
        return snapshot(session, drill)
    before = snapshot(session, drill)
    if payload.expected_sequence is not None and payload.expected_sequence != before["latest_event_sequence"]:
        raise HTTPException(409, "现场已发生新变化，请重新预览后确认。")
    dispatch = {
        "state": (DrillAction, change_state), "event.inject": (EventInject, inject_event),
        "residents.assign": (ResidentCommand, command_residents), "robot.command": (RobotCommand, command_robot),
        "vehicle.command": (VehicleCommand, command_vehicle),
        "search.assign": (SearchAssignment, assign_search), "participant.feedback": (ParticipantAction, participant_action),
        "task.assign": (TaskAssignment, assign_task), "task.action": (TaskAction, director_task_action), "director.configure": (DirectorConfig, configure_director),
    }
    if payload.kind in {"road.reopen", "task.assign", "task.action"} and not payload.target_id:
        raise HTTPException(422, "请选择本场道路或处置任务。")
    labels = {"state": "演练状态已更新", "event.inject": "现场扰动已生效", "road.reopen": "道路通行已恢复", "residents.assign": "居民撤离指令", "robot.command": "机器人指令", "search.assign": "搜索责任已指派", "participant.feedback": "参演反馈已记录", "task.assign": "处置任务已指派", "task.action": "处置任务已更新", "director.configure": "事件导演设置已更新"}
    labels["vehicle.command"] = "应急车辆调度"
    command_record = DrillCommand(
        drill_session_id=drill.id,
        command_id=payload.command_id,
        actor=identity.username,
        kind=payload.kind,
        target_id=payload.target_id,
        command_args=fingerprint["arguments"],
        expected_sequence=payload.expected_sequence,
        status="submitted",
        label=labels[payload.kind],
        reason="指令已提交，正在校验现场状态。",
        submitted_at_seconds=before["elapsed_seconds"],
    )
    session.add(command_record)
    session.flush()
    session.info["drill_command_transaction"] = True
    final_state = None
    try:
        if payload.kind == "road.reopen":
            result = reopen_road(drill_id, payload.target_id, identity, session)
        else:
            schema, handler = dispatch[payload.kind]
            arguments = schema.model_validate(payload.arguments)
            if payload.kind in {"task.assign", "task.action"}:
                result = handler(drill_id, payload.target_id, arguments, identity, session)
            else:
                result = handler(drill_id, arguments, identity, session)
        effects = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill_id, DrillEvent.sequence > before["latest_event_sequence"]).order_by(DrillEvent.sequence)))
        receipt = append_event(session, drill, "command.accepted", identity.username, effects[0].message if effects else labels[payload.kind], {
            **fingerprint, "command_id": payload.command_id, "event_ids": [e.id for e in effects],
            "score_before": before["score_preview"]["total_score"],
            "score_after_acceptance": result["score_preview"]["total_score"],
        })
        all_events = list(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill_id).order_by(DrillEvent.sequence)))
        current_elapsed = effective_elapsed(drill)
        current_simulation = simulation_state(drill, all_events, current_elapsed, session=session)
        current_robot = robot_runtime(session.scalar(select(RobotAgent).where(RobotAgent.drill_session_id == drill.id)), all_events, current_elapsed)
        derived = command_feedback(all_events, current_simulation, current_robot, current_elapsed, drill.status)
        synchronize_records(session, drill, derived, current_elapsed)
        current_feedback = next((item for item in derived if item["id"] == payload.command_id), None)
        if current_feedback:
            apply_feedback(command_record, current_feedback, current_elapsed)
        else:
            command_record.status = "accepted"
            command_record.reason = "指令已受理，等待演练引擎执行。"
            command_record.accepted_at_seconds = receipt.elapsed_seconds
            command_record.event_ids = [e.id for e in effects]
            command_record.score_before = before["score_preview"]["total_score"]
            command_record.score_after_acceptance = result["score_preview"]["total_score"]
        final_state = snapshot(session, drill)
        persist_snapshot(session, drill, final_state, force=True)
        session.commit()
    except ValidationError as exc:
        session.rollback()
        _persist_failed_command(session, drill, payload, identity.username, "validation_error", "指令参数不正确，请核对对象和目标后重试。")
        raise HTTPException(422, "指令参数不正确，请核对对象和目标后重试。") from exc
    except HTTPException as exc:
        session.rollback()
        if exc.status_code < 500:
            detail = exc.detail if isinstance(exc.detail, str) else "指令未通过现场校验。"
            _persist_failed_command(session, drill, payload, identity.username, f"http_{exc.status_code}", detail)
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.info.pop("drill_command_transaction", None)
    return final_state or snapshot(session, drill)


@router.websocket("/ws/drills/{drill_id}")
async def drill_socket(websocket: WebSocket, drill_id: str, token: str | None = None, code: str | None = None, protocol: int = 1, after_sequence: int | None = None):
    username: str | None = None
    if token:
        try:
            with SessionLocal() as auth_session:
                username = authenticate_access_token(token, auth_session).username
        except Exception:
            await websocket.close(code=4401); return
    elif not code or code.upper() != participant_code(drill_id):
        await websocket.close(code=4401); return
    await websocket.accept()
    import asyncio
    previous = None
    heartbeat_at = 0.

    @serialized_command
    def read_catchup():
        if protocol not in {2, 3} or after_sequence is None or after_sequence < 0:
            return None
        with SessionLocal() as session:
            drill = require_drill(session, drill_id, username) if username else require_participant_drill(session, drill_id, code or "")
            latest = session.scalar(select(func.max(DrillEvent.sequence)).where(DrillEvent.drill_session_id == drill.id)) or 0
            if after_sequence >= latest:
                return None
            found = list(session.scalars(
                select(DrillEvent)
                .where(DrillEvent.drill_session_id == drill.id, DrillEvent.sequence > after_sequence)
                .order_by(DrillEvent.sequence)
                .limit(501)
            ))
            complete = len(found) <= 500
            events = found[:500]
            return {
                "type": "drill.catchup",
                "drill_id": drill.id,
                "after_sequence": after_sequence,
                "latest_sequence": latest,
                "complete": complete,
                "events": [{
                    "id": event.id,
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "actor": event.actor,
                    "message": event.message,
                    "elapsed_seconds": event.elapsed_seconds,
                    "payload": {key: value for key, value in event.payload.items() if key not in {"world", "token_hash", "participant_token"}},
                } for event in events],
            }

    @serialized_command
    def read_live():
        # Read version and state under the same process lock as engine/commands.
        # Always acquire command lock before snapshot-cache lock.
        with SessionLocal() as session:
            drill = require_drill(session, drill_id, username) if username else require_participant_drill(session, drill_id, code or "")
            if protocol not in {2, 3}:
                advance_engine(session, drill)
                return snapshot(session, drill)
            # Only the scheduler advances v2 live sessions. Observers never tick it.
            sequence = session.scalar(select(func.max(DrillEvent.sequence)).where(DrillEvent.drill_session_id == drill_id)) or 0
            version = state_version(sequence, effective_elapsed(drill), participant_presence_revision(session, drill.id))
            def compatible_snapshot():
                stored = load_snapshot(session, drill_id, version)
                # Old persisted snapshots predate the fleet projection. Rebuild
                # from frozen world/events without modifying the user's history.
                return stored if stored and stored.get("simulation", {}).get("rescue_projection_version") == 1 else snapshot(session, drill)
            return live_snapshots.get(drill_id, version, compatible_snapshot)

    try:
        catchup = await asyncio.to_thread(read_catchup)
        if catchup:
            await websocket.send_json(catchup)
        while True:
            data = await asyncio.to_thread(read_live)
            now = asyncio.get_running_loop().time()
            if protocol not in {2, 3} or previous is None:
                await websocket.send_json({"type": "drill.snapshot", "data": data})
                heartbeat_at = now
            elif data["state_version"] != previous["state_version"]:
                await websocket.send_json({"type": "drill.delta", "drill_id": drill_id, "base_version": previous["state_version"], "state_version": data["state_version"], "patch": snapshot_patch(previous, data, entities=protocol == 3)})
                heartbeat_at = now
            elif now - heartbeat_at >= 5:
                await websocket.send_json({"type": "drill.heartbeat", "drill_id": drill_id, "state_version": data["state_version"]})
                heartbeat_at = now
            previous = data
            await asyncio.sleep(.25 if protocol in {2, 3} else 1)
    except HTTPException:
        await websocket.close(code=4404)
    except (WebSocketDisconnect, RuntimeError):
        return
