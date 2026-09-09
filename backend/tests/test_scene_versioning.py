from fastapi.testclient import TestClient


def login_headers(client: TestClient) -> dict[str, str]:
    response = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'Zhiyan@2026'})
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def test_editing_published_scene_creates_draft_version(client: TestClient) -> None:
    headers = login_headers(client)
    community = client.post('/api/v1/communities/demo', headers=headers).json()
    objects = client.get(f"/api/v1/communities/{community['id']}/map-objects", headers=headers).json()
    shed = next(item for item in objects if item['object_type'] == 'charging_shed')
    template = next(item for item in client.get('/api/v1/scene-templates', headers=headers).json() if item['code'] == 'night_charging_shed_fire')
    scene = client.post(
        f"/api/v1/communities/{community['id']}/scenes",
        headers=headers,
        json={'template_id': template['id'], 'name': '不可变版本测试'},
    ).json()
    configured = client.patch(
        f"/api/v1/scenes/{scene['id']}/charging-shed-parameters",
        headers=headers,
        json={
            'fire_source_object_id': shed['id'], 'start_time': '20:15', 'wind_direction': '微风',
            'resident_count': 60, 'hydrant_status': 'faulty', 'south_lane_status': 'restricted',
            'stair_width': 1.2,
        },
    ).json()
    assert client.post(f"/api/v1/scenes/{scene['id']}/publish", headers=headers).status_code == 200
    original = configured['versions'][-1]

    response = client.patch(
        f"/api/v1/scenes/{scene['id']}/charging-shed-parameters",
        headers=headers,
        json={
            'fire_source_object_id': shed['id'], 'start_time': '21:30', 'wind_direction': '北风',
            'resident_count': 35, 'hydrant_status': 'available', 'south_lane_status': 'open',
            'stair_width': 1.4,
        },
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated['status'] == 'draft'
    assert len(updated['versions']) == len(configured['versions']) + 1
    assert updated['versions'][-2]['version_number'] == original['version_number']
    assert updated['versions'][-2]['parameters'] == original['parameters']
    assert updated['versions'][-1]['version_number'] == original['version_number'] + 1
    assert updated['versions'][-1]['parameters']['resident_count'] == 35


def test_live_preview_uses_unsaved_parameters_without_creating_version(client: TestClient) -> None:
    headers = login_headers(client)
    demo = client.post('/api/v1/communities/demo', headers=headers).json()
    objects = client.get(f"/api/v1/communities/{demo['id']}/map-objects", headers=headers).json()
    shed = next(item for item in objects if item['object_type'] == 'charging_shed')
    template = next(item for item in client.get('/api/v1/scene-templates', headers=headers).json() if item['code'] == 'night_charging_shed_fire')
    scene = client.post(f"/api/v1/communities/{demo['id']}/scenes", headers=headers, json={'template_id': template['id'], 'name': '实时试算测试'}).json()
    version_count = len(scene['versions'])

    preview = client.post(
        f"/api/v1/scenes/{scene['id']}/preview?minute=4",
        headers=headers,
        json={
            'fire_source_object_id': shed['id'], 'start_time': '22:10', 'wind_direction': '北风',
            'resident_count': 27, 'hydrant_status': 'available', 'south_lane_status': 'blocked',
            'stair_width': 0.8,
        },
    )

    assert preview.status_code == 200
    body = preview.json()
    assert body['simulation']['summary']['total'] == 27
    assert body['simulation']['world']['parameters']['wind_direction'] == '北风'
    assert body['simulation']['world']['spatial_network']['stair_width'] == 0.8
    assert body['simulation']['environment']['east_hydrant'] == 'available'
    assert body['simulation']['environment']['south_lane'] == 'blocked'
    unchanged = client.get(f"/api/v1/communities/{demo['id']}/scenes", headers=headers).json()
    current = next(item for item in unchanged if item['id'] == scene['id'])
    assert len(current['versions']) == version_count
