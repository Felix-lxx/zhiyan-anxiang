"""One command transaction boundary; no dependency on HTTP or API handlers."""
from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations import DrillCommand, DrillEvent, DrillSession
from app.models.agent import AgentRun
from app.domain.errors import CommandRejected
from app.schemas.operations import LiveCommand
from app.services.command_feedback import command_feedback
from app.services.command_ledger import apply_feedback, safe_arguments, same_command, synchronize_records
from app.services.command_lock import serialized_command
from app.services.state_store import persist_snapshot


@dataclass(frozen=True)
class CommandOrigin:
    kind: Literal['director', 'agent'] = 'director'
    plan_id: str | None = None
    revision: int | None = None
    step_id: str | None = None

    def __post_init__(self):
        if self.kind not in {'director', 'agent'}:
            raise ValueError('Unknown command origin')
        if self.kind == 'agent' and (not self.plan_id or not self.step_id or not self.revision):
            raise ValueError('Agent origin requires an approved plan revision and step')


class CommandRuntime(Protocol):
    """Domain operations supplied at composition time. Expected errors are CommandRejected."""
    def require_drill(self, session: Session, drill_id: str, username: str) -> DrillSession: ...
    def snapshot(self, session: Session, drill: DrillSession) -> dict: ...
    def apply(self, session: Session, drill: DrillSession, command: LiveCommand, identity: Any) -> dict: ...
    def append_event(self, session: Session, drill: DrillSession, kind: str, actor: str, message: str, payload: dict) -> DrillEvent: ...
    def elapsed(self, drill: DrillSession) -> int: ...
    def simulation(self, session: Session, drill: DrillSession, events: list, elapsed: int) -> dict: ...
    def robot(self, session: Session, drill: DrillSession, events: list, elapsed: int) -> dict | None: ...


LABELS = {
    'indoor.door.set': '室内房门状态已更新',
    'state': '演练状态已更新', 'event.inject': '现场扰动已生效', 'road.reopen': '道路通行已恢复',
    'residents.assign': '居民撤离指令', 'robot.command': '机器人指令', 'vehicle.command': '应急车辆调度',
    'search.assign': '搜索责任已指派', 'participant.feedback': '参演反馈已记录',
    'task.assign': '处置任务已指派', 'task.action': '处置任务已更新', 'director.configure': '事件导演设置已更新',
}


class DrillCommandApplication:
    def __init__(self, runtime: CommandRuntime):
        self.runtime = runtime

    def _authorize_agent(self, session, drill_id, payload, identity, origin):
        if origin.kind != 'agent':
            return
        run = session.get(AgentRun, origin.plan_id)
        if (not run or run.drill_session_id != drill_id or run.actor != identity.username
                or run.status not in {'executing', 'waiting'}
                or run.approved_revision != origin.revision or run.revision != origin.revision):
            raise CommandRejected(409, '目标计划的批准或执行归属已变化，请重新核对计划。')
        step = next((s for s in run.steps if s['id'] == origin.step_id and s['command_id'] == payload.command_id), None)
        kind = step.get('kind', 'residents.assign') if step else None
        arguments = (step['arguments'] if kind in {'robot.command', 'indoor.door.set'} else
                     {key: step[key] for key in ('resident_ids', 'exit', 'action')}) if step else None
        if not step or kind != payload.kind or arguments != payload.arguments or payload.target_id is not None:
            raise CommandRejected(409, '指令对象或参数与已批准步骤不一致，请重新比较方案。')
        from app.services.agent_claims import authorize
        authorize(session, run)

    def _persist_failure(self, session, drill, payload, actor, code, reason, origin):
        current = session.get(DrillSession, drill.id)
        if current is None:
            return
        existing = session.scalar(select(DrillCommand).where(
            DrillCommand.drill_session_id == current.id, DrillCommand.command_id == payload.command_id))
        if existing:
            return
        reason = ' '.join(str(reason).split())[:500]
        event = self.runtime.append_event(session, current, 'command.failed', actor, f'指令未执行：{reason}', {
            'command_id': payload.command_id, 'kind': payload.kind, 'target_id': payload.target_id,
            'failure_code': code, 'origin': asdict(origin),
        })
        at = self.runtime.elapsed(current)
        session.add(DrillCommand(
            drill_session_id=current.id, command_id=payload.command_id, actor=actor, kind=payload.kind,
            target_id=payload.target_id, command_args=safe_arguments(payload.arguments),
            expected_sequence=payload.expected_sequence, status='failed', label='指令未执行', reason=reason,
            progress=0, submitted_at_seconds=at, completed_at_seconds=at, event_ids=[event.id], failure_code=code))
        session.flush()
        persist_snapshot(session, current, self.runtime.snapshot(session, current), force=True)
        session.commit()

    @serialized_command
    def execute(self, session: Session, drill_id: str, payload: LiveCommand, identity: Any,
                origin: CommandOrigin | None = None) -> dict:
        runtime, origin = self.runtime, origin or CommandOrigin()
        drill = runtime.require_drill(session, drill_id, identity.username)
        session.execute(select(DrillSession.id).where(DrillSession.id == drill_id).with_for_update())
        record = session.scalar(select(DrillCommand).where(
            DrillCommand.drill_session_id == drill_id, DrillCommand.command_id == payload.command_id))
        if record:
            if record.actor != identity.username or not same_command(record, payload.kind, payload.arguments, payload.target_id):
                raise CommandRejected(409, '该指令编号已用于另一项操作，请重新提交。')
            if record.status == 'failed':
                raise CommandRejected(409, f'该指令此前未执行：{record.reason} 请重新预览并下达新指令。')
            return runtime.snapshot(session, drill)
        receipts = session.scalars(select(DrillEvent).where(
            DrillEvent.drill_session_id == drill_id, DrillEvent.event_type == 'command.accepted'))
        prior = next((event for event in receipts if event.payload.get('command_id') == payload.command_id), None)
        fingerprint = {'kind': payload.kind, 'arguments': safe_arguments(payload.arguments), 'target_id': payload.target_id}
        if prior:
            if prior.actor != identity.username or any(prior.payload.get(key) != value for key, value in fingerprint.items()):
                raise CommandRejected(409, '该指令编号已用于另一项操作，请重新提交。')
            return runtime.snapshot(session, drill)
        self._authorize_agent(session, drill_id, payload, identity, origin)
        before = runtime.snapshot(session, drill)
        if payload.expected_sequence is not None and payload.expected_sequence != before['latest_event_sequence']:
            raise CommandRejected(409, '现场已发生新变化，请重新预览后确认。')
        if payload.kind in {'road.reopen', 'task.assign', 'task.action'} and not payload.target_id:
            raise CommandRejected(422, '请选择本场道路或处置任务。')
        record = DrillCommand(
            drill_session_id=drill.id, command_id=payload.command_id, actor=identity.username,
            kind=payload.kind, target_id=payload.target_id, command_args=fingerprint['arguments'],
            expected_sequence=payload.expected_sequence, status='submitted', label=LABELS[payload.kind],
            reason='指令已提交，正在校验现场状态。', submitted_at_seconds=before['elapsed_seconds'])
        session.add(record)
        session.flush()
        session.info['drill_command_transaction'] = True
        session.info['command_origin'] = origin
        try:
            result = runtime.apply(session, drill, payload, identity)
            effects = list(session.scalars(select(DrillEvent).where(
                DrillEvent.drill_session_id == drill_id, DrillEvent.sequence > before['latest_event_sequence']
            ).order_by(DrillEvent.sequence)))
            receipt = runtime.append_event(session, drill, 'command.accepted', identity.username,
                effects[0].message if effects else LABELS[payload.kind], {
                    **fingerprint, 'command_id': payload.command_id, 'origin': asdict(origin),
                    'event_ids': [e.id for e in effects], 'score_before': before['score_preview']['total_score'],
                    'score_after_acceptance': result['score_preview']['total_score'],
                })
            events = list(session.scalars(select(DrillEvent).where(
                DrillEvent.drill_session_id == drill_id).order_by(DrillEvent.sequence)))
            # apply() returns the authoritative post-action projection. The new
            # receipt changes bookkeeping, not motion; reuse this same instant
            # instead of advancing the world again while accepting one command.
            at = result['elapsed_seconds']
            simulation = result['simulation']
            robot = result['robot']
            derived = command_feedback(events, simulation, robot, at, drill.status)
            synchronize_records(session, drill, derived, at)
            feedback = next((item for item in derived if item['id'] == payload.command_id), None)
            if feedback:
                apply_feedback(record, feedback, at)
            else:
                record.status, record.reason = 'accepted', '指令已受理，等待演练引擎执行。'
                record.accepted_at_seconds = receipt.elapsed_seconds
                record.event_ids = [e.id for e in effects]
                record.score_before = before['score_preview']['total_score']
                record.score_after_acceptance = result['score_preview']['total_score']
            final = runtime.snapshot(session, drill)
            persist_snapshot(session, drill, final, force=True)
            session.commit()
            return final
        except ValidationError as exc:
            session.rollback()
            reason = '指令参数不正确，请核对对象和目标后重试。'
            self._persist_failure(session, drill, payload, identity.username, 'validation_error', reason, origin)
            raise CommandRejected(422, reason) from exc
        except CommandRejected as exc:
            session.rollback()
            if exc.status_code < 500:
                self._persist_failure(session, drill, payload, identity.username,
                                      f'http_{exc.status_code}', exc.detail, origin)
            raise
        except Exception:
            session.rollback()
            raise
        finally:
            session.info.pop('drill_command_transaction', None)
            session.info.pop('command_origin', None)
