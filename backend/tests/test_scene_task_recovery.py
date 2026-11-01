from sqlalchemy import delete, func, select

from app.api.routes import operations
from app.core.config import get_settings
from app.models.tasks import DecisionTask


def legacy_scene(client):
    token = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': get_settings().bootstrap_admin_password}).json()['access_token']
    headers = {'Authorization': 'Bearer '+token}
    demo = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    scenes = client.get('/api/v1/communities/'+demo['community']['id']+'/scenes', headers=headers).json()
    scene = next(s for s in scenes if s['id'] == demo['scene_id'])
    root = '/api/v1/scenes/'+scene['id']
    old_world = client.get('/api/v1/drills/'+demo['drill_id'], headers=headers).json()['simulation']['world']
    with operations.SessionLocal() as db:
        db.execute(delete(DecisionTask).where(DecisionTask.scene_version_id == scene['versions'][-1]['id']))
        db.commit()
    return headers, demo, scene, root, old_world


def task_count(version_id):
    with operations.SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(DecisionTask).where(DecisionTask.scene_version_id == version_id))


def test_repair_recovers_published_preview_without_rewriting_frozen_history(client):
    headers, demo, original, root, old_world = legacy_scene(client)
    assert client.get(root+'/preview', headers=headers).status_code == 422
    assert client.post(root+'/publish', headers=headers).status_code == 422
    repaired = client.post(root+'/repair-tasks', headers=headers)
    assert repaired.status_code == 200, repaired.text
    scene = repaired.json()
    assert scene['status'] == 'draft'
    assert len(scene['versions']) == len(original['versions'])+1
    version_id = scene['versions'][-1]['id']
    assert task_count(version_id) == 3
    assert task_count(original['versions'][-1]['id']) == 0
    assert client.get(root+'/preview', headers=headers).status_code == 200
    again = client.post(root+'/repair-tasks', headers=headers).json()
    assert again['versions'][-1]['id'] == version_id
    assert task_count(version_id) == 3
    assert client.post(root+'/publish', headers=headers).status_code == 200
    created = client.post(root+'/drills', headers=headers, json={'name': '修复后新场次'})
    assert created.status_code == 201, created.text
    assert len(created.json()['tasks']) == 3
    assert client.get('/api/v1/drills/'+demo['drill_id'], headers=headers).json()['simulation']['world'] == old_world


def test_saving_legacy_parameters_repairs_only_editable_tasks_and_is_idempotent(client):
    headers, _, original, root, _ = legacy_scene(client)
    parameters = original['versions'][-1]['parameters']
    first = client.patch(root+'/parameters', headers=headers, json=parameters)
    assert first.status_code == 200, first.text
    scene = first.json()
    version_id = scene['versions'][-1]['id']
    assert task_count(version_id) == 3
    second = client.patch(root+'/parameters', headers=headers, json=parameters)
    assert second.status_code == 200
    assert second.json()['versions'][-1]['id'] == version_id
    assert task_count(version_id) == 3
    assert client.get(root+'/preview', headers=headers).status_code == 200
