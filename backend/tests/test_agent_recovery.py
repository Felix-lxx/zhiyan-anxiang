"""A revision changes future decisions, not already accepted physical actions."""
from types import SimpleNamespace
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillCommand, DrillEvent
from app.services.agent_workflow import advance_run
from test_agent_workflow import proposal, robot_proposal
from test_exercise_world import exercise  # noqa: F401


@pytest.mark.parametrize("arrive_during_review", [False, True])
def test_replan_reuses_owned_robot_receipt_without_recharging(exercise, arrive_during_review):
    client, headers, demo, root, _, _, clock, tick, _ = exercise
    run, candidate = robot_proposal(exercise)
    url = root + '/agent/runs/' + run['id'] + '/actions'

    def action(kind, revision, **extra):
        response = client.post(url, headers=headers, json={'action': kind, 'revision': revision, **extra})
        assert response.status_code == 200, response.text
        return response.json()

    begun = action('approve', 1, candidate_id=candidate['id'])
    robot_steps = [s for s in begun['steps'] if s.get('kind') == 'robot.command']
    original = client.get(root, headers=headers).json()
    task = next(t for t in original['robot']['task_queue'] if t['status'] == 'executing')
    reviewing = action('review', 1)
    assert reviewing['status'] == 'needs_review' and reviewing['revision'] == 2
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run['id'])
        before = list(db.scalars(select(DrillCommand.command_id)))
        advance_run(db, record, SimpleNamespace(username='admin'))
        assert list(db.scalars(select(DrillCommand.command_id))) == before
    if arrive_during_review:
        tick(task['ends_at_seconds'])
    else:
        tick(clock['t'] + 2)
    current = client.get(root, headers=headers).json()
    compared = action('replan', 2)
    selected = next(c for c in compared['candidates'] if c['can_apply'])
    support = selected['robot_support']
    assert support['reusing_task'] and support['battery_required'] == 3
    assert support['already_arrived'] == arrive_during_review
    if arrive_during_review:
        assert support['route_points'] == []
    else:
        assert support['route_points'][0] == {'x':current['robot']['x'], 'y':current['robot']['y']}
    assert support['duration_seconds'] == max(0, task['ends_at_seconds'] - clock['t'])
    assert compared['recovery']['remaining'] + compared['recovery']['retained_arrived'] == compared['summary']['total']
    resumed = action('approve', compared['revision'], candidate_id=selected['id'])
    assert [s['command_id'] for s in resumed['steps'] if s.get('kind') == 'robot.command'] == [s['command_id'] for s in robot_steps]
    after = client.get(root, headers=headers).json()
    assert after['robot']['battery'] == current['robot']['battery'] - (3 if arrive_during_review else 0)
    assert [t['id'] for t in after['robot']['task_queue']] == [t['id'] for t in original['robot']['task_queue']]
    if not arrive_during_review:
        tick(task['ends_at_seconds'])
        with operations.SessionLocal() as db:
            advance_run(db, db.get(AgentRun, run['id']), SimpleNamespace(username='admin'))
    with operations.SessionLocal() as db:
        broadcasts = list(db.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == demo['drill_id'],
            DrillEvent.event_type == 'robot.broadcast_completed')))
        assert len(broadcasts) == 1


def test_manual_takeover_during_review_cannot_be_reclaimed(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    ids = [p['id'] for p in data['simulation']['residents'] if not p['vulnerable']][:2]
    run = proposal(client, headers, root, ids)
    candidate = next(c for c in run['candidates'] if c['can_apply'])
    url = root + '/agent/runs/' + run['id'] + '/actions'
    assert client.post(url, headers=headers, json={'action':'approve', 'revision':1, 'candidate_id':candidate['id']}).status_code == 200
    assert client.post(url, headers=headers, json={'action':'review', 'revision':1}).status_code == 200
    assert client.post(root + '/residents', headers=headers, json={'resident_ids':ids, 'exit':'south', 'action':'evacuate'}).status_code == 200
    response = client.post(url, headers=headers, json={'action':'replan', 'revision':2})
    assert response.status_code == 409
    view = client.get(root + '/agent/runs', headers=headers).json()['runs'][0]
    assert view['status'] == 'taken_over'


def test_recovery_preserves_active_escort_identity_and_position(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    ids = [p['id'] for p in data['simulation']['residents'] if p['vulnerable']][:2]
    assert ids
    run = proposal(client, headers, root, ids)
    candidate = next(c for c in run['candidates'] if c['can_apply'])
    url = root + '/agent/runs/' + run['id'] + '/actions'
    assert client.post(url, headers=headers, json={'action':'approve', 'revision':1, 'candidate_id':candidate['id']}).status_code == 200
    before = client.get(root, headers=headers).json()['simulation']
    escorts = {h['resident_id']:(h['staff_id'],h['x'],h['y'],h['height']) for h in before['helpers'] if h['resident_id'] in ids}
    assert escorts
    assert client.post(url, headers=headers, json={'action':'review', 'revision':1}).status_code == 200
    response = client.post(url, headers=headers, json={'action':'replan', 'revision':2})
    assert response.status_code == 200, response.text
    compared = response.json()
    assert compared['recovery']['active_escorts'] == len(escorts)
    selected = next(c for c in compared['candidates'] if c['can_apply'])
    assert client.post(url, headers=headers, json={'action':'approve', 'revision':compared['revision'], 'candidate_id':selected['id']}).status_code == 200
    after = client.get(root, headers=headers).json()['simulation']
    assert {h['resident_id']:(h['staff_id'],h['x'],h['y'],h['height']) for h in after['helpers'] if h['resident_id'] in ids} == escorts
    for p in before['residents']:
        updated = next(q for q in after['residents'] if q['id'] == p['id'])
        assert (updated['x'],updated['y'],updated.get('height')) == (p['x'],p['y'],p.get('height'))


def test_replan_cannot_erase_missing_escort_evidence(exercise, monkeypatch):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    ids = [p['id'] for p in data['simulation']['residents'] if p['vulnerable']][:2]
    assert len(ids) == 2
    run = proposal(client, headers, root, ids)
    candidate = next(c for c in run['candidates'] if c['can_apply'])
    url = root + '/agent/runs/' + run['id'] + '/actions'
    assert client.post(url, headers=headers, json={'action':'approve', 'revision':1, 'candidate_id':candidate['id']}).status_code == 200
    assert client.post(url, headers=headers, json={'action':'review', 'revision':1}).status_code == 200
    # Exercise the validation with one arrived target and one still on route.
    current = deepcopy(client.get(root, headers=headers).json())
    person = next(p for p in current['simulation']['residents'] if p['id'] == ids[0])
    person.update(status='evacuated', assisted=False)
    monkeypatch.setattr(operations, 'snapshot', lambda *args, **kwargs: current)
    response = client.post(url, headers=headers, json={'action':'replan', 'revision':2})
    assert response.status_code == 409 and '不能通过重规划抹去缺项' in response.json()['detail']
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run['id'])
        assert record.status == 'needs_review' and record.revision == 2
        assert record.scope['resident_ids'] == ids
