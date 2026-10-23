"""Transactional drill-scoped claims, separate from short-lived worker leases.

All writers lock the drill first. Claims survive restart, while physical queues
remain authoritative after stop/review/manual takeover. No TTL can steal an actor.
"""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import select, update, or_
from sqlalchemy.dialects import postgresql, sqlite
from app.models.agent import AgentResourceClaim, AgentRun
from app.domain.errors import CommandRejected
from app.services.response_staff import roster

LIVE = {'executing', 'waiting', 'needs_review', 'awaiting_approval', 'awaiting_rollcall'}


class ResourceBusy(Exception):
    pass


def release(session, run_id):
    session.execute(update(AgentResourceClaim).where(AgentResourceClaim.run_id == run_id)
                    .values(run_id=None, revision=None, updated_at=datetime.now(UTC)))


def claims_for(session, drill_id):
    return list(session.scalars(select(AgentResourceClaim).where(AgentResourceClaim.drill_session_id == drill_id)))


def acquire(session, run, data):
    """All or nothing after the caller's drill row lock; never commits internally."""
    rows = claims_for(session, run.drill_session_id)
    owners = {r.id: r for r in session.scalars(select(AgentRun).where(AgentRun.id.in_(
        {row.run_id for row in rows if row.run_id})))}
    for row in rows:
        if row.run_id and (not owners.get(row.run_id) or owners[row.run_id].status not in LIVE):
            row.run_id, row.revision = None, None
    by_key = {row.resource_key: row for row in rows}
    people = {p['id']: p for p in data['simulation']['residents']}
    required = {f'resident:{pid}': people[pid]['label'] for pid in run.scope['resident_ids']
                if pid in people and people[pid]['status'] != 'evacuated'}
    robot_steps = [s for s in run.steps if s.get('kind') == 'robot.command' and s['status'] != 'completed']
    if robot_steps:
        required['robot:R-01'] = '巡检广播机器人 R-01'
    required.update({'door:'+s['arguments']['door_id']: s['label'] for s in run.steps
        if s.get('kind') == 'indoor.door.set' and s['status'] != 'completed'})
    escorts = [s for s in run.steps if s.get('action') == 'priority_assist' and s['status'] != 'completed']
    slots = max((len(s['resident_ids']) for s in escorts), default=0)
    helpers = [h for h in data['simulation'].get('helpers', []) if h['state'] != 'completed']
    own_helpers = {h.get('staff_id') for h in helpers if h['resident_id'] in run.scope['resident_ids']}
    foreign_helpers = {h.get('staff_id') for h in helpers if h['resident_id'] not in run.scope['resident_ids']}
    available = []
    for slot in roster(data['simulation']['world']):
        owner = by_key.get('staff:' + slot['id'])
        if slot.get('available', True) and slot['id'] not in foreign_helpers and (not owner or owner.run_id in {None, run.id}):
            available.append(slot)
    available.sort(key=lambda slot: (slot['id'] not in own_helpers, slot['id']))
    if len(available) < slots:
        return False, f'等待值守资源：本批需要 {slots} 名，目前可归属 {len(available)} 名；未重复派遣。'
    selected = available[:max(slots, len(own_helpers))]
    required.update({'staff:' + s['id']: s['name'] for s in selected})
    for key, name in required.items():
        row = by_key.get(key)
        if row and row.run_id not in {None, run.id}:
            return False, f'等待{name}：已归属其他活动计划；未追加或覆盖任务。'
    contract = run.scope.get('resource_contract')
    if (contract and set(contract['keys']) == set(required) and all(
            key in by_key and by_key[key].run_id == run.id and by_key[key].revision == run.approved_revision
            for key in required)):
        return True, '沿用本计划已登记资源，不重复预占。'
    # Ensure stable slots with an atomic dialect-specific insert. The unique key
    # is the final protection even when different workers race on SQLite.
    insert = sqlite.insert if session.get_bind().dialect.name == 'sqlite' else postgresql.insert
    try:
        with session.begin_nested():
            for key, name in sorted(required.items()):
                session.execute(insert(AgentResourceClaim).values(id=str(uuid4()), drill_session_id=run.drill_session_id,
                    resource_key=key, resource_name=name, updated_at=datetime.now(UTC)).on_conflict_do_nothing(
                        index_elements=['drill_session_id', 'resource_key']))
                changed = session.execute(update(AgentResourceClaim).where(
                    AgentResourceClaim.drill_session_id == run.drill_session_id,
                    AgentResourceClaim.resource_key == key,
                    or_(AgentResourceClaim.run_id.is_(None), AgentResourceClaim.run_id == run.id)).values(
                        run_id=run.id, revision=run.approved_revision, acquired_at_seconds=data['elapsed_seconds'],
                        updated_at=datetime.now(UTC)))
                if changed.rowcount != 1:
                    raise ResourceBusy()
            session.execute(update(AgentResourceClaim).where(AgentResourceClaim.run_id == run.id,
                AgentResourceClaim.resource_key.not_in(list(required))).values(run_id=None, revision=None,
                    updated_at=datetime.now(UTC)))
    except ResourceBusy:
        return False, '资源在批准时已被占用，整批预占已撤回；等待释放后继续。'
    run.scope = {**run.scope, 'resource_contract': {'version': 1, 'keys': sorted(required),
                'staff_ids': [s['id'] for s in selected]}}
    session.flush()
    return True, '批准资源已登记，按真实回执执行。'


def authorize(session, run):
    contract = run.scope.get('resource_contract')
    if not contract:  # Plans approved before P4 continue their durable receipts.
        return
    owned = {r.resource_key for r in claims_for(session, run.drill_session_id)
             if r.run_id == run.id and r.revision == run.approved_revision}
    if not set(contract['keys']).issubset(owned):
        raise CommandRejected(409, '资源归属已变化，未提交新指令，请重新核对计划。')


def staff_assignments(session, drill_id, data, resident_ids, run_id=None):
    """Freeze actual staff IDs into the domain event, shared by physics and view."""
    claims = {row.resource_key: row.run_id for row in claims_for(session, drill_id) if row.run_id}
    helpers = {h['resident_id']: h for h in data.get('helpers', []) if h['state'] != 'completed'}
    busy = {h.get('staff_id') for h in helpers.values()}
    available = [s['id'] for s in roster(data['world']) if s.get('available', True) and s['id'] not in busy
                 and (claims.get('staff:' + s['id']) == run_id if run_id else claims.get('staff:' + s['id']) is None)]
    result = {}
    for pid in resident_ids:
        if pid in helpers:
            result[pid] = helpers[pid]['staff_id']
        elif available:
            result[pid] = available.pop(0)
        else:
            raise CommandRejected(409, '值守员已在执行或归属其他计划，请等待释放；未生成虚拟护送员。')
    return result


def manual_takeover(session, drill_id, kind, arguments, at):
    keys = ({'robot:R-01'} if kind == 'robot.command' else
            {'door:'+arguments['door_id']} if kind == 'indoor.door.set' else
            {'resident:' + pid for pid in arguments.get('resident_ids', [])} if kind == 'residents.assign' else set())
    owners = {row.run_id for row in claims_for(session, drill_id) if row.run_id and row.resource_key in keys}
    for run_id in owners:
        run = session.get(AgentRun, run_id)
        run.status, run.reason = 'taken_over', '人工调度已接管资源，本计划停止后续自动下令；已受理动作保留。'
        run.execution_epoch += 1
        run.updated_at = datetime.now(UTC)
        from app.models.agent import AgentRunEvent
        session.add(AgentRunEvent(run_id=run_id, kind='taken_over', message=run.reason, elapsed_seconds=at))
        release(session, run_id)


def resource_view(session, run):
    contract = run.scope.get('resource_contract', {})
    keys = set(contract.get('keys', []))
    rows = [r for r in claims_for(session, run.drill_session_id) if r.run_id == run.id or r.resource_key in keys]
    return {'version': 1, 'items': [{'key': r.resource_key, 'name': r.resource_name,
        'kind': r.resource_key.split(':', 1)[0], 'state': 'owned' if r.run_id == run.id else 'occupied' if r.run_id else 'released',
        'revision': r.revision} for r in rows if not r.resource_key.startswith('resident:')],
        'resident_count': sum(r.run_id == run.id and r.resource_key.startswith('resident:') for r in rows)}
