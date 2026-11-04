"""Task guidance reads the execution contract without submitting an action."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.main import app
from app.api.routes.auth import get_current_identity
from app.services.task_guidance import guidance_view
from app.services.agent_tool_planning import planning_context
from test_agent_tool_planning import proposal
from test_exercise_world import exercise


@pytest.mark.parametrize(('drill_status', 'task_status', 'ready', 'expected'), [
    ('ready', 'waiting', False, 'wait'),
    ('paused', 'verifying', True, 'resume'),
    ('running', 'pending', False, 'accept'),
    ('running', 'executing', False, 'arrive'),
    ('running', 'verifying', False, 'wait'),
    ('running', 'verifying', True, 'submit'),
    ('ended', 'verifying', True, 'review'),
    ('ended', 'completed', True, 'completed'),
])
def test_next_action_preserves_real_task_and_clock_conditions(drill_status, task_status, ready, expected):
    task = {'id': 'task-1', 'title': '关闭燃气', 'kind': 'gas_off', 'status': task_status,
            'verification_ready': ready, 'can_submit': ready, 'steps': ['检查并提交证据'],
            'blockers': [] if ready else ['尚未达到处置时长']}
    data = {'id': 'drill-1', 'elapsed_seconds': 23, 'latest_event_sequence': 7, 'status': drill_status}
    original = deepcopy(task)
    result = guidance_view(data, task)
    assert result['next_action']['kind'] == expected
    assert result['can_submit'] == (drill_status == 'running' and ready and task_status != 'completed')
    assert result['observed_at_seconds'] == 23
    assert result['event_sequence'] == 7
    assert next(c for c in result['conditions'] if c['id'] == 'evidence')['met'] == (task_status == 'completed')
    assert task == original


def test_guidance_authorization_pinned_references_and_no_domain_side_effect(exercise):
    client, headers, _, root, _, _, _, tick, _ = exercise
    before = tick(0)
    task = before['tasks'][0]
    endpoint = root + '/tasks/' + task['id'] + '/guidance'
    assert client.post(endpoint, json={}).status_code == 401
    assert client.post(endpoint, headers=headers, json={'action': 'submit'}).status_code == 422
    assert client.post(root + '/tasks/not-in-this-drill/guidance', headers=headers, json={}).status_code == 404
    app.dependency_overrides[get_current_identity] = lambda: SimpleNamespace(username='outsider')
    try:
        assert client.post(endpoint, json={}).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_identity)
    response = client.post(endpoint, headers=headers, json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['task_id'] == task['id']
    assert result['next_action']['kind'] == 'wait'
    assert result['knowledge']['hits']
    for hit in result['knowledge']['hits']:
        document = client.get('/api/v1/knowledge/documents/' + hit['document_id'], headers=headers).json()
        version = next(v for v in document['versions'] if v['id'] == hit['version_id'])
        assert any(c['id'] == hit['chunk_id'] and c['content_hash'] == hit['content_hash'] for c in version['chunks'])
    after = client.get(root, headers=headers).json()
    for key in ('status', 'elapsed_seconds', 'latest_event_sequence', 'tasks', 'events', 'commands'):
        assert after.get(key) == before.get(key), key


def test_model_tool_receives_human_task_contract_without_mutating_proposal():
    value = proposal()
    value['task_graph'] = {'case_tasks': [{'id': 'gas', 'kind': 'gas_off', 'status': 'verifying',
        'blockers': ['燃气处置尚未核验'], 'can_submit': False}], 'human_gate': '责任人提交处置事实'}
    context = planning_context(value)['compare_candidates']
    assert context['case_tasks'] == value['task_graph']['case_tasks']
    assert context['human_gate'] == value['task_graph']['human_gate']
    context['case_tasks'][0]['blockers'].clear()
    assert value['task_graph']['case_tasks'][0]['blockers'] == ['燃气处置尚未核验']
