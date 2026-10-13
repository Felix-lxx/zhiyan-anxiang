from fastapi.testclient import TestClient


def ready(client):
    token = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'Zhiyan@2026'}).json()['access_token']
    headers = {'Authorization': f'Bearer {token}'}
    data = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    return headers, data


def test_history_index_does_not_run_simulation(client: TestClient, monkeypatch):
    headers, data = ready(client)
    def forbidden(*args, **kwargs):
        raise AssertionError('History indexes must not calculate simulation snapshots')
    monkeypatch.setattr('app.api.routes.operations.snapshot', forbidden)
    response = client.get(f"/api/v1/scenes/{data['scene_id']}/drills?summary=true", headers=headers)
    assert response.status_code == 200
    row = response.json()[0]
    assert row['id'] == data['drill_id']
    assert row['resident_count'] == 60
    assert row['created_at'] and row['score'] is None
    assert 'simulation' not in row
    assert client.get(f"/api/v1/scenes/{data['scene_id']}/drills?summary=true").status_code == 401


def test_join_code_and_exception_report(client: TestClient):
    headers, data = ready(client)
    drill_id = data['drill_id']
    code = drill_id[-6:].upper()
    resolved = client.get('/api/v1/participant/resolve', params={'code': ' '+code.lower()+' '})
    assert resolved.status_code == 200 and resolved.json()['drill_id'] == drill_id
    assert client.get('/api/v1/participant/resolve?code=bad').status_code == 422
    member = client.post(f'/api/v1/participant/drills/{drill_id}/join?code={code}', json={'role': '物业/网格员', 'display_name': '测试处置组'}).json()
    heartbeat = client.post(f'/api/v1/participant/drills/{drill_id}/heartbeat?code={code}', json={'participant_token': member['token']})
    assert heartbeat.status_code == 200 and heartbeat.json()['online'] is True
    presence = client.get(f'/api/v1/participant/drills/{drill_id}?code={code}').json()
    property_role = next(item for item in presence['participants'] if item['role'] == '物业/网格员')
    assert property_role['online_count'] == 1
    assert property_role['members'][0]['name'] == '测试处置组'
    path = f'/api/v1/participant/drills/{drill_id}/actions?code={code}'
    payload = {'role': '物业/网格员', 'action': 'report', 'message': '北门附近道路受阻，请求导演核查。', 'participant_token': member['token']}
    assert client.post(path, json=payload).status_code == 409
    client.patch(f'/api/v1/drills/{drill_id}/state', headers=headers, json={'action':'start'})
    report = client.post(path, json=payload)
    assert report.status_code == 200
    assert any(e['event_type']=='participant.report' and payload['message'] in e['message'] for e in report.json()['events'])
    assert client.post(path, json={**payload, 'participant_token':'invalid'}).status_code == 403
    assert client.post(f'/api/v1/participant/drills/{drill_id}/leave?code={code}', json={'participant_token': member['token']}).status_code == 200
    presence = client.get(f'/api/v1/participant/drills/{drill_id}?code={code}').json()
    assert next(item for item in presence['participants'] if item['role'] == '物业/网格员')['online_count'] == 0
    client.patch(f'/api/v1/drills/{drill_id}/state', headers=headers, json={'action':'end'})
    assert client.get('/api/v1/participant/resolve', params={'code':code}).status_code == 404
