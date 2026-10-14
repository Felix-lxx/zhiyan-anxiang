"""One bounded delivery chain through real API handlers and an isolated database."""
from test_exercise_world import exercise
from app.api.routes import operations
from app.models.operations import DrillSession


def test_saved_preparation_escort_rollcall_and_replay(exercise):
    client, headers, demo, old_root, _, _, clock, old_tick, _ = exercise
    old_world = old_tick(0)['simulation']['world']
    scene = '/api/v1/scenes/' + demo['scene_id']
    parameters = {**old_world['parameters'], 'resident_count': 6,
                  'stair_width': 1.2, 'south_lane_status': 'open', 'hydrant_status': 'available'}

    def request(method, url, **kwargs):
        response = client.request(method, url, headers=headers, **kwargs)
        assert response.is_success, response.text
        return response.json()

    request('PATCH', scene + '/charging-shed-parameters', json=parameters)
    assert request('POST', scene + '/validate')['passed']
    request('POST', scene + '/publish')
    preview = request('GET', scene + '/preview')['simulation']
    created = request('POST', scene + '/drills', json={'name': '准备到复盘执行链验收'})
    drill_id = created['id']
    root = '/api/v1/drills/' + drill_id
    assert created['simulation']['world'] == preview['world']
    assert created['simulation']['summary']['total'] == 6
    assert request('GET', old_root)['simulation']['world'] == old_world

    def tick(t):
        clock['t'] = t
        with operations.SessionLocal() as session:
            operations.advance_engine(session, session.get(DrillSession, drill_id))
        return request('GET', root)

    request('PATCH', root + '/state', json={'action': 'start'})
    first = tick(0)
    robot_arrival = first['robot']['task_queue'][0]['ends_at_seconds']
    for t in (robot_arrival, robot_arrival + 2, robot_arrival + 4):
        current = tick(t)
    assert any(e['event_type'] == 'robot.alarm_confirmed' for e in current['events'])
    residents = current['simulation']['residents']
    target = next(p for p in residents if p['vulnerable'])
    others = [p['id'] for p in residents if p['id'] != target['id']]
    request('POST', root + '/residents', json={'resident_ids': others, 'exit': 'north', 'action': 'evacuate'})
    commanded = request('POST', root + '/commands', json={
        'command_id': 'delivery-escort', 'kind': 'residents.assign',
        'arguments': {'resident_ids': [target['id']], 'exit': 'north', 'action': 'priority_assist'},
    })
    assert commanded['simulation']['helpers'][0]['state'] == 'approaching'
    assert not next(p for p in commanded['simulation']['residents'] if p['id'] == target['id'])['assisted']
    early = client.post(root + '/participant-actions', headers=headers, json={
        'role': '居民代表', 'action': 'resident_counted', 'message': '未到集合点不能提前清点',
        'resident_ids': [target['id']],
    })
    assert early.status_code == 409

    power_task = next(t for t in current['tasks'] if t['kind'] == 'power_off')
    task_url = root + '/tasks/' + power_task['id'] + '/actions'
    for action in ('accept', 'arrive'):
        request('POST', task_url, json={'action': action})
    tick(clock['t'] + 8)
    done = request('POST', task_url, json={'action': 'submit', 'evidence': '现场断电并复核充电棚电源指示状态'})
    assert done['simulation']['environment']['power_off']

    states, spaces = set(), {target['indoor_stage']}
    for t in range(clock['t'] + 1, clock['t'] + 301, 3):
        current = tick(t)
        helper = current['simulation']['helpers'][0]
        person = next(p for p in current['simulation']['residents'] if p['id'] == target['id'])
        states.add(helper['state'])
        spaces.add(person['indoor_stage'])
        if current['simulation']['summary']['evacuated'] == 6:
            break
    assert {'escorting', 'completed'} <= states, (states, helper, person)
    assert {'room', 'stairs', 'outdoor'} <= spaces, spaces
    assert current['simulation']['summary']['evacuated'] == 6, current['simulation']['summary']
    counted = request('POST', root + '/participant-actions', json={
        'role': '居民代表', 'action': 'resident_counted', 'message': '集合区域已逐人核验全部六名居民',
        'resident_ids': [p['id'] for p in residents],
    })
    assert counted['simulation']['summary']['counted'] == 6
    ended = request('PATCH', root + '/state', json={'action': 'end'})
    replay = request('GET', root + '/replay?at_seconds=' + str(clock['t']))
    assert replay['simulation']['summary'] == ended['simulation']['summary']
    assert any(e['event_type'] == 'participant.resident_counted' for e in ended['events'])
    assert ended['score'] is not None
    assert next(t for t in replay['tasks'] if t['id'] == power_task['id'])['evidence'] == '现场断电并复核充电棚电源指示状态'
