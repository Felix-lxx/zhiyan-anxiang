from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillStateSnapshot
from app.services.agent_contract import validate_goal_capabilities, goal_constraints
from app.services.snapshot_codec import encode_snapshot, decode_snapshot
from app.services.state_store import load_snapshot
from app.maintenance.compact_snapshots import compact_snapshots
from test_exercise_world import exercise


@pytest.mark.parametrize('goal', [
    '组织全部居民疏散，并转运伤员送医',
    '疏散居民并转运伤员送医', '派救护车接运伤员',
    '不要走北门并安排医疗移交',
])
def test_unsupported_subgoals_are_not_silently_dropped(goal):
    with pytest.raises(HTTPException) as error:
        validate_goal_capabilities(goal)
    assert error.value.status_code == 422
    assert '尚未接入自动编排' in error.value.detail


@pytest.mark.parametrize('goal', [
    '厨房火灾，优先护送三层居民', '疏散灭火器旁的居民',
    '不安排消防车喷水灭火，只疏散居民', '疏散居民，消防车不要喷水',
])
def test_fire_context_and_explicit_exclusions_are_supported(goal):
    validate_goal_capabilities(goal)


@pytest.mark.parametrize('goal,requested,excluded', [
    ('疏散居民并派消防车到火点连接水源喷水灭火', True, False),
    ('不要走北门并派消防车喷水后疏散居民', True, False),
    ('不安排消防车喷水灭火，只疏散居民', False, True),
    ('疏散居民，消防车不要喷水', False, True),
])
def test_firetruck_intent_preserves_requests_and_exclusions(goal, requested, excluded):
    validate_goal_capabilities(goal)
    scope = goal_constraints(SimpleNamespace(goal=goal))
    assert scope['vehicle_suppression'] is requested
    assert scope['vehicle_suppression_forbidden'] is excluded


def test_excluded_spray_never_enters_candidate_actions(exercise):
    client, headers, _, root, _, _, _, tick, _ = exercise
    selected = [p['id'] for p in tick(0)['simulation']['residents'] if not p['vulnerable']][:2]
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id':'excluded-spray-001', 'goal':'不安排消防车喷水，只疏散居民',
        'resident_ids':selected, 'priority_assist':False, 'robot_broadcast':False})
    assert response.status_code == 201, response.text
    assert response.json()['candidates']
    assert all(not candidate.get('vehicle_support') for candidate in response.json()['candidates'])


def test_goal_rejected_before_model_and_legacy_plan_cannot_be_approved(exercise, monkeypatch):
    from app.api.routes import agent
    client, headers, demo, root, _, _, _, tick, _ = exercise
    before = tick(0)
    original_interpret = agent.interpret_goal
    monkeypatch.setattr(agent, 'interpret_goal', lambda *a: pytest.fail('unsupported goal called provider'))
    mixed = '组织居民疏散，并转运伤员送医'
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id': 'mixed-rejected-001', 'goal': mixed, 'use_model': True, 'pause_for_review': True})
    assert response.status_code == 422
    after = client.get(root, headers=headers).json()
    assert after['status'] == before['status']
    assert after['latest_event_sequence'] == before['latest_event_sequence']
    monkeypatch.setattr(agent, 'interpret_goal', original_interpret)
    created = client.post(root+'/agent/runs', headers=headers, json={
        'request_id': 'legacy-valid-001', 'goal': '组织居民疏散', 'use_model': False})
    assert created.status_code == 201, created.text
    plan = created.json()
    with operations.SessionLocal() as db:
        run = db.get(AgentRun, plan['id']); run.goal = mixed; db.commit()
    read = client.get(root+'/agent/runs', headers=headers).json()['runs'][0]
    assert read['approval_guard']['can_approve'] is False
    assert '未编排部分' in read['approval_guard']['reason']
    response = client.post(root+'/agent/runs/'+plan['id']+'/actions', headers=headers,
        json={'action': 'approve', 'revision': plan['revision'], 'candidate_id': plan['candidates'][0]['id']})
    assert response.status_code == 422


def test_sqlite_sessions_return_utc_and_saved_preview_returns_checked_version(exercise):
    client, headers, demo, root, _, _, _, _, _ = exercise
    sessions = client.get('/api/v1/auth/sessions', headers=headers).json()
    for item in sessions:
        for key in ('created_at', 'last_used_at', 'expires_at'):
            assert datetime.fromisoformat(item[key].replace('Z', '+00:00')).utcoffset().total_seconds() == 0
    recent = datetime.fromisoformat(sessions[0]['last_used_at'].replace('Z', '+00:00'))
    assert abs((datetime.now(UTC)-recent).total_seconds()) < 30
    preview = client.get('/api/v1/scenes/'+demo['scene_id']+'/preview', headers=headers).json()
    direct = client.post('/api/v1/scenes/'+demo['scene_id']+'/validate', headers=headers).json()
    assert preview['configuration_validation'] == direct
    assert direct['passed'] and direct['version_number'] >= 1
    compressed = client.get(root, headers={**headers, 'Accept-Encoding': 'gzip'})
    assert compressed.headers['content-encoding'] == 'gzip'
    assert compressed.json()['id'] == demo['drill_id']


def test_real_legacy_snapshots_compact_without_changing_restored_state(exercise):
    client, headers, demo, root, _, _, _, _, start = exercise
    start()
    with operations.SessionLocal() as db:
        row = db.scalar(select(DrillStateSnapshot).where(DrillStateSnapshot.drill_session_id == demo['drill_id']))
        original = decode_snapshot(row.payload)
        row.payload = original; db.commit()
        before = load_snapshot(db, demo['drill_id'])
        estimate = compact_snapshots(db)
        assert estimate['changed'] >= 1 and not estimate['applied']
        db.expire_all()
        assert '_snapshot_encoding' not in db.get(DrillStateSnapshot, row.id).payload
        result = compact_snapshots(db, apply=True)
        assert result['after_bytes'] < result['before_bytes'] * .5
        assert load_snapshot(db, demo['drill_id']) == before
        assert compact_snapshots(db, apply=True)['changed'] == 0
        assert compact_snapshots(db, apply=True, restore_json=True)['changed'] >= 1
        assert load_snapshot(db, demo['drill_id']) == before


def test_codec_roundtrip_and_corrupt_cache_fallback():
    original = {'state_version': 'sample', '_engine_checkpoint': {'people': [{'x': 1.25}] * 300},
                'simulation': {'residents': [{'label': '居民', 'route': list(range(50))}] * 300}}
    packed = encode_snapshot(original)
    assert len(json.dumps(packed)) < len(json.dumps(original)) * .2
    assert decode_snapshot(packed) == original
    assert decode_snapshot(original) == original
    assert decode_snapshot({**packed, 'data': 'invalid'}) is None
    assert decode_snapshot({**packed, 'decoded_bytes': 2}) is None
