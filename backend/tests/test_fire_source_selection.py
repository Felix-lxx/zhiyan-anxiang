"""P2: one selected object drives preview, freeze, patrol, tasks and history."""
import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.domain import CommunityVersion, MapObject, MapObjectType, SceneVersion
from app.models.operations import DrillSession
from app.services.exercise_world import capture_world
from app.services.fire_sources import InvalidFireSource


@pytest.fixture
def scenario(client):
    login = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'Zhiyan@2026'})
    headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
    demo = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    root = '/api/v1/scenes/' + demo['scene_id']
    old = client.get('/api/v1/drills/' + demo['drill_id'], headers=headers).json()
    world = old['simulation']['world']
    with operations.SessionLocal() as db:
        alternate = MapObject(community_version_id=world['community_version_id'], object_type=MapObjectType.CHARGING_SHED,
                              name='西侧备用充电棚', geometry={'x': 12, 'y': 70}, properties={'width': 8, 'depth': 4})
        db.add(alternate); db.commit(); alternate_id = alternate.id
    return client, headers, demo, root, world, alternate_id


def test_selected_source_drives_preview_freeze_patrol_tasks_and_immutable_replay(scenario):
    client, headers, demo, root, original, alternate = scenario
    candidates = client.get(root + '/fire-sources', headers=headers)
    assert candidates.status_code == 200
    assert alternate in [source['id'] for source in candidates.json()]
    payload = {**original['parameters'], 'fire_source_object_id': alternate}
    preview = client.post(root + '/preview?minute=1', headers=headers, json=payload)
    assert preview.status_code == 200, preview.text
    predicted = preview.json()['simulation']['world']
    assert predicted['fire_origin'] == {'x': 12, 'y': 70}
    assert predicted['fire_source']['location']['object_id'] == alternate
    assert predicted['inspection_target'] == predicted['fire_source']['access_position']
    power_task = next(task for task in predicted['tasks'] if task['kind'] == 'power_off')
    assert power_task['target_object_id'] == alternate
    assert power_task['target_position'] == predicted['inspection_target']
    assert power_task['target'] == '西侧备用充电棚'
    before_save = client.get('/api/v1/communities/' + demo['community']['id'] + '/scenes', headers=headers).json()
    assert next(scene for scene in before_save if scene['id'] == demo['scene_id'])['versions'][-1]['parameters']['fire_source_object_id'] != alternate

    saved = client.patch(root + '/charging-shed-parameters', headers=headers, json=payload)
    assert saved.status_code == 200, saved.text
    params = saved.json()['versions'][-1]['parameters']
    assert params['fire_source']['location']['object_id'] == alternate
    assert params['fire_source']['location']['community_version_id'] == original['community_version_id']
    restored = client.get(root + '/preview?minute=1', headers=headers).json()['simulation']['world']
    assert restored['fire_source'] == predicted['fire_source']
    assert client.post(root + '/publish', headers=headers).status_code == 200
    new = client.post(root + '/drills', headers=headers, json={'name': '备用棚火点演练'}).json()
    world = new['simulation']['world']
    assert world['fire_source'] == predicted['fire_source']
    assert client.patch('/api/v1/drills/' + new['id'] + '/state', headers=headers, json={'action': 'start'}).status_code == 200
    with operations.SessionLocal() as db:
        operations.advance_engine(db, db.get(DrillSession, new['id']))
    started = client.get('/api/v1/drills/' + new['id'], headers=headers).json()
    queue = started['robot']['task_queue']
    assert queue and queue[0]['route_points'][-1] == world['inspection_target']
    with operations.SessionLocal() as db:
        source = db.get(MapObject, alternate); source.geometry = {'x': 80, 'y': 80}; db.commit()
    for drill_id, expected in [(demo['drill_id'], original), (new['id'], world)]:
        replay = client.get('/api/v1/drills/' + drill_id + '/replay?at_seconds=0', headers=headers)
        assert replay.status_code == 200, replay.text
        assert replay.json()['simulation']['world'] == expected


def test_invalid_source_never_falls_back_or_accepts_untrusted_address(scenario):
    client, headers, demo, root, original, alternate = scenario
    with operations.SessionLocal() as db:
        version = db.get(SceneVersion, original['scene_version_id'])
        building = db.scalar(select(MapObject).where(MapObject.community_version_id == version.community_version_id,
                                                    MapObject.object_type == MapObjectType.BUILDING))
        other_version = CommunityVersion(community_id=demo['community']['id'], version_number=2, name='另一底图版本')
        db.add(other_version); db.flush()
        foreign = MapObject(community_version_id=other_version.id, object_type=MapObjectType.CHARGING_SHED,
                            name='另一版本的棚', geometry={'x': 12, 'y': 70}, properties={})
        db.add(foreign); db.commit()
        invalid_ids = ['deleted-source', building.id, foreign.id]
        for source_id in invalid_ids:
            with pytest.raises(InvalidFireSource):
                capture_world(db, version, {'fire_source_object_id': source_id})
    listed = client.get(root + '/fire-sources', headers=headers).json()
    assert foreign.id not in [source['id'] for source in listed]
    for source_id in invalid_ids:
        payload = {**original['parameters'], 'fire_source_object_id': source_id}
        assert client.patch(root + '/charging-shed-parameters', headers=headers, json=payload).status_code == 422
        assert client.post(root + '/preview', headers=headers, json=payload).status_code == 422
    payload = {**original['parameters'], 'fire_source_object_id': alternate,
               'fire_source': {'location': {'object_id': 'forged'}, 'position': {'x': 99, 'y': 99}}}
    result = client.post(root + '/preview', headers=headers, json=payload)
    assert result.status_code == 200
    assert result.json()['simulation']['world']['fire_source']['position'] == {'x': 12, 'y': 70}


def test_source_coordinate_failure_is_shared_by_prepare_publish_and_freeze(scenario):
    client, headers, demo, root, original, alternate = scenario
    with operations.SessionLocal() as db:
        source = db.get(MapObject, original['parameters']['fire_source_object_id'])
        source.geometry = {'x': 150, 'y': 40}; db.commit()
    validation = client.post(root + '/validate', headers=headers).json()
    assert not validation['passed']
    assert validation['issue_details'][0]['query']['field'] == 'fire-source'
    assert client.get(root + '/preview', headers=headers).status_code == 422
    assert client.post(root + '/publish', headers=headers).status_code == 422
    assert client.post(root + '/drills', headers=headers, json={'name': '无效坐标'}).status_code == 422
