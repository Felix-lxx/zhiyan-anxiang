import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.domain import MapObject, SceneVersion, RoadNode
from app.models.operations import DrillEvent, DrillSession
from app.services.drill_simulation import plan_route, clear_segment


@pytest.fixture
def exercise(client, monkeypatch):
    clock = {"t": 0}
    monkeypatch.setattr(operations, "effective_elapsed", lambda d: clock["t"] if d.status != "ready" else 0)
    token = client.post('/api/v1/auth/login', json={"username": "admin", "password": "Zhiyan@2026"}).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    demo = client.post('/api/v1/communities/demo-ready', headers=headers).json()
    root = '/api/v1/drills/' + demo["drill_id"]
    invite = client.post(root + '/participant-invite', headers=headers).json()["code"]
    public = '/api/v1/participant/drills/' + demo["drill_id"]
    def tick(t):
        clock["t"] = t
        # The scheduler owns advancement; opening GET /drills is now read-only.
        with operations.SessionLocal() as session:
            operations.advance_engine(session, session.get(DrillSession, demo["drill_id"]))
        response = client.get(root, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()
    def start_and_confirm():
        assert client.patch(root + '/state', headers=headers, json={"action": "start"}).status_code == 200
        first = tick(0)
        assert first["robot"]["task_queue"][0]["status"] == "executing"
        arrival = first["robot"]["task_queue"][0]["ends_at_seconds"]
        for t in [arrival, arrival + 2, arrival + 4]:
            result = tick(t)
        assert any(e["event_type"] == "robot.alarm_confirmed" for e in result["events"])
        return result
    return client, headers, demo, root, public, invite, clock, tick, start_and_confirm


def test_frozen_configuration_drives_population_geometry_and_old_replay(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    first = tick(0)
    assert first["simulation"]["summary"]["total"] == 60
    world = first["simulation"]["world"]
    assert len(world["objects"]) == 14
    source_id = world["parameters"]["fire_source_object_id"]
    with operations.SessionLocal() as db:
        source = db.get(MapObject, source_id)
        source.geometry = {"x": 90, "y": 5}
        version = db.get(SceneVersion, world["scene_version_id"])
        version.parameters = {**version.parameters, "resident_count": 9}
        node = db.get(RoadNode, world["road_network"]["nodes"][0]["id"])
        node.x = 2
        db.commit()
    same = tick(0)
    assert same["simulation"]["world"] == world
    new = client.post('/api/v1/scenes/' + demo["scene_id"] + '/drills', headers=headers, json={"name": "修改配置后创建"}).json()
    assert new["simulation"]["summary"]["total"] == 9
    assert new["simulation"]["world"]["fire_origin"] == {"x": 90, "y": 5}
    assert client.get(root + '/replay?at_seconds=0', headers=headers).json()["simulation"]["world"] == world


def test_perception_task_identity_evidence_and_replay(exercise):
    client, headers, demo, root, public, code, clock, tick, start = exercise
    data = start()
    assert len([e for e in data["events"] if e["event_type"] == "robot.sensor_sample"]) == 3
    task = next(t for t in data["tasks"] if t["kind"] == "power_off")
    join = lambda role: client.post(public + '/join?code=' + code, json={"role": role, "display_name": role + '测试员'}).json()
    owner, foreign = join('物业/网格员'), join('居民代表')
    assigned = client.post(root + '/commands', headers=headers, json={
        'command_id': 'assign-property-task-001', 'kind': 'task.assign', 'target_id': task['id'],
        'arguments': {'participant_id': owner['participant_id']},
    })
    assert assigned.status_code == 200, assigned.text
    assigned_task = next(item for item in assigned.json()['tasks'] if item['id'] == task['id'])
    assert assigned_task['assignee_id'] == owner['participant_id']
    assert assigned_task['assignee'] == '物业/网格员测试员'
    def act(action, member=owner, evidence=''):
        return client.post(public + '/tasks/' + task["id"] + '/actions?code=' + code, json={"action": action, "participant_token": member["token"], "evidence": evidence})
    assert act('accept', foreign).status_code == 403
    assert act('submit').status_code == 409
    assert client.patch(root + '/tasks/' + task["id"] + '/complete', headers=headers).status_code == 409
    assert act('accept').status_code == 200
    competitor = join('物业/网格员')
    assert act('accept', competitor).status_code == 409
    assert act('arrive').status_code == 200
    at_arrival = clock["t"]
    assert act('submit', evidence='已断开电源并核对指示状态').status_code == 409
    tick(at_arrival + 8)
    assert act('submit', evidence='少字').status_code == 422
    done = act('submit', evidence='已断开电源并核对指示状态')
    assert done.status_code == 200, done.text
    assert done.json()["simulation"]["environment"]["power_off"] is True
    assert act('submit', evidence='重复处置证据再次提交').status_code == 200
    assert len([e for e in tick(clock["t"])["events"] if e["event_type"] == "task.completed"]) == 1
    assert 'token_hash' not in str(done.json()) and owner["token"] not in str(done.json())
    before = client.get(root + '/replay?at_seconds=' + str(at_arrival), headers=headers).json()
    assert before["simulation"]["environment"]["power_off"] is False
    after = client.get(root + '/replay?at_seconds=' + str(clock["t"]), headers=headers).json()
    assert after["simulation"] == done.json()["simulation"]
    assert next(t for t in after["tasks"] if t["id"] == task["id"])["evidence"] == '已断开电源并核对指示状态'
    tick(at_arrival + 300)
    overdue = tick(clock["t"])
    assert any(e["event_type"] == 'task.overdue' for e in overdue["events"])


def test_reopen_road_and_helpers_are_continuous(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    data = start()
    at = clock["t"]
    person = next(p for p in data["simulation"]["residents"] if p["vulnerable"])
    command = client.post(root + '/residents', headers=headers, json={"resident_ids": [person["id"]], "exit": "north", "action": "priority_assist"})
    assert command.status_code == 200, command.text
    helper = command.json()["simulation"]["helpers"][0]
    assert helper["state"] == 'approaching'
    same_person = next(p for p in command.json()["simulation"]["residents"] if p["id"] == person["id"])
    assert (same_person["x"], same_person["y"]) == (person["x"], person["y"])
    later = tick(at + 4)
    assert later["simulation"]["helpers"][0]["x"] != helper["x"]
    edge = next(e for e in later["simulation"]["road_network"]["edges"] if '南门' in e["name"])
    assert client.post(root + '/inject', headers=headers, json={"event_type": "channel_blocked", "road_edge_id": edge["id"]}).status_code == 200
    assert client.post(root + '/roads/' + edge["id"] + '/reopen', headers=headers).status_code == 200
    opened = tick(clock["t"])
    assert next(e for e in opened["simulation"]["road_network"]["edges"] if e["id"] == edge["id"])["status"] == 'open'
    assert not any(b["road_edge_id"] == edge["id"] for b in opened["simulation"]["environment"]["blockages"])


def test_selective_rollcall_and_result_scoring(exercise):
    client, headers, demo, root, public, code, clock, tick, start = exercise
    data = start()
    with operations.SessionLocal() as db:
        drill = db.get(operations.DrillSession, demo["drill_id"])
        for person in ['resident-3', 'resident-8']:
            operations.append_event(db, drill, 'inject.resident_missing', '测试', '指定居民失联', {"resident_id": person})
        db.commit()
    member = client.post(public + '/join?code=' + code, json={"role": '居民代表', "display_name": '居民甲'}).json()
    endpoint = public + '/actions?code=' + code
    body = {"role": '居民代表', "action": 'resident_counted', "message": '已核验居民位置并恢复联系', "participant_token": member['token']}
    assert client.post(endpoint, json=body).status_code == 422
    result = client.post(endpoint, json={**body, "resident_ids": ['resident-3']})
    # V3 rollcall is an assembly receipt, not a remote way to clear missing people.
    assert result.status_code == 409
    result = client.get(root, headers=headers)
    assert result.json()['simulation']['summary']['missing'] == 2
    assert client.post(endpoint, json={**body, "role": '物业/网格员', "resident_ids": ['resident-8']}).status_code == 403
    old_score = result.json()['score_preview']['total_score']
    edge = result.json()['simulation']['road_network']['edges'][0]
    block = client.post(root + '/inject', headers=headers, json={"event_type": "channel_blocked", "road_edge_id": edge['id']}).json()
    assert block['score_preview']['total_score'] <= old_score


def test_building_obstacles_block_connectors():
    box = {"x": 5, "y": 5, "width": 4, "depth": 4}
    assert not clear_segment((0, 5), (10, 5), [box])
    assert clear_segment((0, 1), (10, 1), [box])
    network = {"nodes": [{"id": 'a', "name": '入口', "x": 0, "y": 0}], "edges": [], "obstacles": [box]}
    assert len(plan_route(network, (0, 0), (5, 5))[1]) == 1


def test_complete_main_case_and_historical_branch(exercise):
    client, headers, demo, root, public, code, clock, tick, start = exercise
    data = start()
    tasks = {task['kind']: task for task in data['tasks']}
    def act(kind, action):
        response = client.post(root + '/tasks/' + tasks[kind]['id'] + '/actions', headers=headers,
                               json={'action': action, 'evidence': '现场完成核验并记录处置结果'})
        assert response.status_code == 200, response.text
        return response.json()
    for kind in tasks:
        act(kind, 'accept')
        act(kind, 'arrive')
    checkpoint = clock['t']
    vulnerable = [p['id'] for p in data['simulation']['residents'] if p['vulnerable']]
    response = client.post(root + '/residents', headers=headers, json={'resident_ids': vulnerable, 'exit': 'north', 'action': 'priority_assist'})
    assert response.status_code == 200, response.text
    tick(checkpoint + 8)
    act('power_off', 'submit')
    target = tasks['broadcast']['target_position']
    move = client.post(root + '/robot', headers=headers, json={'command': 'move', **target, 'target': '广播入口'})
    assert move.status_code == 200, move.text
    tick(move.json()['robot']['task_queue'][-1]['ends_at_seconds'] + 1)
    assert client.post(root + '/robot', headers=headers, json={'command': 'broadcast'}).status_code == 200
    act('broadcast', 'submit')
    final = tick(clock['t'] + 450)
    assert final['simulation']['summary']['evacuated'] == 60
    assert all(h['state'] == 'completed' for h in final['simulation']['helpers'])
    act('escort', 'submit')
    client.post(public + '/join?code=' + code, json={'role': '居民代表', 'display_name': '证据验证员'})
    comparison = client.post(root + '/branches/compare', headers=headers, json={'at_seconds': checkpoint}).json()
    assert comparison['source_state']['elapsed_seconds'] == checkpoint
    assert comparison['worlds']['baseline']['environment']['power_off'] is False
    assert client.post(root + '/branches/compare', headers=headers, json={'at_seconds': clock['t'] + 1}).status_code == 422
    assert client.patch(root + '/state', headers=headers, json={'action': 'end'}).status_code == 200
    report = client.get(root + '/report', headers=headers).json()
    assert all(t['status'] == 'completed' for t in report['tasks'])
    assert 'token_hash' not in str(report) and 'participant_token' not in str(report)


def test_single_resident_missing_does_not_crash():
    from app.services.drill_simulation import simulate_residents
    network = {'nodes': [], 'edges': []}
    world = {'fire_origin': {'x': 0, 'y': 0}, 'residents': [{'id': 'resident-1', 'x': 1, 'y': 1}]}
    result = simulate_residents(network, [{'sequence': 1, 'elapsed_seconds': 0, 'event_type': 'inject.resident_missing', 'payload': {}}], 0, world=world)
    assert result['summary']['missing'] == 1
