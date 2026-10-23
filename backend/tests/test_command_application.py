from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.application.drill_commands import CommandOrigin, CommandRejected
from app.bootstrap.commands import command_application
from app.models.operations import DrillCommand, DrillEvent
from app.schemas.operations import LiveCommand
from test_agent_workflow import proposal
from test_exercise_world import exercise


def test_http_and_application_share_idempotent_receipt_and_original_origin(exercise):
    client, headers, demo, root, _, _, _, _, start = exercise
    start()
    body = {'command_id': 'application-shared-001', 'kind': 'residents.assign',
            'arguments': {'resident_ids': ['resident-1'], 'exit': 'north'}}
    response = client.post(root + '/commands', headers=headers, json=body)
    assert response.status_code == 200, response.text
    first = response.json()
    command = next(c for c in first['commands'] if c['id'] == body['command_id'])
    assert command['origin']['kind'] == 'director'
    with operations.SessionLocal() as db:
        application = command_application()
        same = application.execute(db, demo['drill_id'], LiveCommand(**body), SimpleNamespace(username='admin'))
        assert same['latest_event_sequence'] == first['latest_event_sequence']
        assert len(list(db.scalars(select(DrillCommand).where(DrillCommand.command_id == body['command_id'])))) == 1
        with pytest.raises(CommandRejected) as conflict:
            application.execute(db, demo['drill_id'], LiveCommand(**{**body, 'arguments': {'resident_ids': ['resident-1'], 'exit': 'south'}}), SimpleNamespace(username='admin'))
        assert conflict.value.status_code == 409
        with pytest.raises(CommandRejected) as forbidden:
            application.execute(db, demo['drill_id'], LiveCommand(**body), SimpleNamespace(username='other-account'))
        assert forbidden.value.status_code == 404


def test_agent_uses_application_without_calling_http_command_entry(exercise, monkeypatch):
    client, headers, demo, root, _, _, _, _, start = exercise
    data = start()
    ids = [p['id'] for p in data['simulation']['residents'] if not p['vulnerable']][:2]
    run = proposal(client, headers, root, ids)
    candidate = next(c for c in run['candidates'] if c['can_apply'])
    def reject_http_entry(*args, **kwargs):
        raise AssertionError('Background execution must not invoke the HTTP command entry')
    monkeypatch.setattr(operations, 'execute_live_command', reject_http_entry)
    monkeypatch.setattr(operations, 'command_residents', reject_http_entry)
    monkeypatch.setattr(operations, 'command_robot', reject_http_entry)
    response = client.post(root + '/agent/runs/' + run['id'] + '/actions', headers=headers,
        json={'action': 'approve', 'revision': run['revision'], 'candidate_id': candidate['id']})
    assert response.status_code == 200, response.text
    state = client.get(root, headers=headers).json()
    commands = [c for c in state['commands'] if (c.get('origin') or {}).get('plan_id') == run['id']]
    assert commands and all(c['origin']['kind'] == 'agent' and c['origin']['revision'] == run['revision'] for c in commands)
    step_ids = {s['id'] for s in response.json()['steps']}
    assert all(c['origin']['step_id'] in step_ids for c in commands)
    with operations.SessionLocal() as db:
        events = list(db.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == demo['drill_id'], DrillEvent.event_type == 'command.accepted')))
        assert any(e.payload.get('origin', {}).get('plan_id') == run['id'] for e in events)


def test_agent_origin_requires_plan_metadata():
    with pytest.raises(ValueError):
        CommandOrigin('agent')


def test_unapproved_agent_origin_cannot_create_domain_commands(exercise):
    client, headers, demo, root, _, _, _, _, start = exercise
    data = start()
    ids = [p['id'] for p in data['simulation']['residents'] if not p['vulnerable']][:1]
    run = proposal(client, headers, root, ids)
    before = client.get(root, headers=headers).json()['latest_event_sequence']
    with operations.SessionLocal() as db:
        with pytest.raises(CommandRejected) as error:
            command_application().execute(db, demo['drill_id'], LiveCommand(
                command_id='agent-unapproved-001', kind='residents.assign',
                arguments={'resident_ids': ids, 'exit': 'north', 'action': 'evacuate'}),
                SimpleNamespace(username='admin'), CommandOrigin('agent', run['id'], run['revision'], 'invented-step'))
        assert error.value.status_code == 409
        assert not list(db.scalars(select(DrillCommand)))
    assert client.get(root, headers=headers).json()['latest_event_sequence'] == before
