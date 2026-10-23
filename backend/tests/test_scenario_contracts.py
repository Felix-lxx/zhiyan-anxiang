from copy import deepcopy

from sqlalchemy import select

from app.api.routes import operations
from app.models.domain import Scene, SceneTemplate
from app.services.scenario_contracts import canonical_defaults, contract_for


def login(client):
    token = client.post('/api/v1/auth/login', json={
        'username': 'admin', 'password': 'Zhiyan@2026'}).json()['access_token']
    return {'Authorization': 'Bearer ' + token}


def test_supported_contract_creates_canonical_draft_and_freezes_metadata(client):
    headers = login(client)
    demo = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    templates = client.get('/api/v1/scene-templates', headers=headers).json()
    template = next(t for t in templates if t['code'] == 'night_charging_shed_fire')
    assert template['capabilities']['can_run'] and template['capabilities']['source_types'] == ['charging_shed']
    scene = client.post(f"/api/v1/communities/{demo['community']['id']}/scenes", headers=headers,
                        json={'template_id': template['id'], 'name': '统一案例契约'}).json()
    assert scene['capabilities'] == template['capabilities']
    defaults = scene['versions'][-1]['parameters']
    assert defaults['start_time'] == '20:15' and defaults['wind_direction'] == '微风'
    assert 'time' not in defaults and 'wind' not in defaults
    root = '/api/v1/drills/' + demo['drill_id']
    world = client.get(root, headers=headers).json()['simulation']['world']
    assert world['scenario_contract'] == template['capabilities']
    assert client.get(root + '/replay?at_seconds=0', headers=headers).json()['simulation']['world'] == world


def test_kitchen_contract_is_available_after_compartment_engine_delivery(client):
    headers = login(client)
    community = client.post('/api/v1/communities/demo', headers=headers).json()
    templates = client.get('/api/v1/scene-templates', headers=headers).json()
    kitchen = next(t for t in templates if t['code'] == 'kitchen_fire')
    assert kitchen['capabilities']['status'] == 'available'
    assert kitchen['capabilities']['can_create'] and kitchen['capabilities']['can_run']
    base = f"/api/v1/communities/{community['id']}/scenes"
    before = client.get(base, headers=headers).json()
    response = client.post(base, headers=headers, json={'template_id': kitchen['id'], 'name': '厨房尚未开放'})
    assert response.status_code == 201
    assert len(client.get(base, headers=headers).json()) == len(before)+1


def test_legacy_kitchen_cannot_run_as_shed_but_frozen_replay_stays_readable(client):
    headers = login(client)
    demo = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    root = '/api/v1/drills/' + demo['drill_id']
    before = client.get(root + '/replay?at_seconds=0', headers=headers).json()['simulation']['world']
    with operations.SessionLocal() as db:
        scene = db.get(Scene, demo['scene_id'])
        kitchen = db.scalar(select(SceneTemplate).where(SceneTemplate.code == 'kitchen_fire'))
        scene.template_id = kitchen.id
        parameters = deepcopy(scene.versions[-1].parameters)
        db.commit()
    base = '/api/v1/scenes/' + demo['scene_id']
    checked = client.post(base + '/validate', headers=headers).json()
    assert not checked['passed']
    assert any(issue['key'] == 'fire_source_type' for issue in checked['issue_details'])
    for path in ['/preview', '/publish', '/drills']:
        if path == '/preview':
            response = client.get(base + path, headers=headers)
        else:
            response = client.post(base + path, headers=headers, json={'name': '应阻止新场次'})
        assert response.status_code == 422, response.text
    response = client.post(base + '/preview', headers=headers, json=parameters)
    assert response.status_code == 422
    response = client.patch(base + '/charging-shed-parameters', headers=headers, json=parameters)
    assert response.status_code == 422
    assert client.get(root + '/replay?at_seconds=0', headers=headers).json()['simulation']['world'] == before


def test_unknown_contract_is_disabled_and_explicit_defaults_win():
    assert not contract_for('custom_unimplemented').available
    assert canonical_defaults({'time': '20:15', 'start_time': '18:00', 'wind': '微风', 'wind_direction': '北风'}) == {
        'start_time': '18:00', 'wind_direction': '北风'}
