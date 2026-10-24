from copy import deepcopy
from app.services.spatial_simulation import simulate
from app.services.presentation import drill_label
from test_exercise_world import exercise
from test_kitchen_fire import kitchen
from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillSession
from app.services.agent_workflow import advance_run
from types import SimpleNamespace
import json


def test_exterior_smoke_does_not_penetrate_unmodelled_rooms(exercise):
    _, _, _, _, _, _, _, tick, _ = exercise
    world = tick(0)['simulation']['world']
    assert world['outdoor_smoke_domain'] == 'exterior_v1'
    current = simulate(world, [], 120)
    assert all(p['smoke_exposure'] == 0 for p in current['residents'])
    legacy = deepcopy(world)
    legacy.pop('outdoor_smoke_domain')
    old = simulate(legacy, [], 120)
    assert any(p['smoke_exposure'] > 0 for p in old['residents'])
    events = [{'sequence': 1, 'elapsed_seconds': 12, 'event_type': 'resident.command',
               'payload': {'resident_ids': [p['id'] for p in world['residents']], 'exit': 'north', 'action': 'evacuate'}}]
    walking = simulate(world, events, 90)
    assert any(p['smoke_exposure'] > 0 for p in walking['residents'])


def test_optional_refresh_does_not_mask_required_authentication(client):
    assert client.post('/api/v1/auth/refresh?optional=true').status_code == 204
    assert client.post('/api/v1/auth/refresh').status_code == 401


def test_old_kitchen_label_is_corrected_without_mutation():
    name = '安巷社区夜间充电棚火灾演练'
    assert drill_label(name, {'parameters': {'fire_source_type': 'kitchen'}}) == '安巷社区住宅厨房火灾演练'
    assert drill_label(name, None) == name


def test_fixture_history_is_recoverable_and_counts_match(exercise):
    client, headers, demo, root, _, _, _, _, _ = exercise
    from app.models.domain import Scene
    with operations.SessionLocal() as db:
        db.get(Scene, demo['scene_id']).name = '实跑验收 · 充电棚火灾'
        db.commit()
    url = '/api/v1/communities/'+demo['community']['id']+'/drill-history'
    hidden = client.get(url+'?include_test=false', headers=headers).json()
    shown = client.get(url+'?include_test=true', headers=headers).json()
    assert hidden['total'] == hidden['matched'] == len(hidden['items']) == 0
    assert hidden['latest_unfinished'] is None
    assert shown['total'] == shown['matched'] == len(shown['items']) == 1
    assert client.get(root, headers=headers).is_success


def complete_case(client, headers, root, tick, indoor=False):
    def call(method, suffix='', body=None):
        response = client.request(method, root + suffix, headers=headers, **({'json': body} if body is not None else {}))
        assert response.is_success, response.text
        return response.json()
    call('PATCH', '/state', {'action': 'start'})
    first = tick(0)
    arrival = first['robot']['task_queue'][0]['ends_at_seconds']
    for at in (arrival, arrival + 2, arrival + 4):
        state = tick(at)
    assert any(e['event_type'] == 'robot.alarm_confirmed' for e in state['events'])
    if indoor:
        env = state['simulation']['environment']['indoor']
        door = next(d for d in env['doors'] if d['room_id'] == env['source_zone_id'])
        call('POST', '/commands', {'command_id':'audit-source-door-open', 'kind':'indoor.door.set',
             'arguments':{'door_id':door['id'], 'state':'open'}})
    run = call('POST', '/agent/runs', {'request_id':'audit-full-decision', 'goal':'疏散全部居民并护送重点人员',
        'priority_assist':True, 'robot_broadcast':True, 'pause_for_review':True, 'include_case_tasks':True})
    choices = [c for c in run['candidates'] if c['can_apply']]
    assert choices
    chosen = next((c for c in choices if c['allocation']['rule']=='containment'), choices[0]) if indoor else choices[0]
    call('POST', '/agent/runs/'+run['id']+'/actions', {'action':'approve','revision':run['revision'],'candidate_id':chosen['id']})
    call('POST', '/participant-actions', {'role':'应急指挥人员','action':'acknowledge','message':'确认火情并启动响应'})
    start = state['elapsed_seconds']
    for at in range(start + 2, start + 650, 3):
        state = tick(at)
        with operations.SessionLocal() as db:
            advance_run(db, db.get(AgentRun,run['id']), SimpleNamespace(username='admin'))
        state = call('GET')
        for task in state['tasks']:
            url = '/tasks/'+task['id']+'/actions'
            if task['status']=='pending':
                state = call('POST',url,{'action':'accept'})
                state = call('POST',url,{'action':'arrive'})
            elif task['status']=='verifying' and task['can_submit']:
                state = call('POST',url,{'action':'submit','evidence':'已按现场要求完成处置并复核结果'})
        ids = [p['id'] for p in state['simulation']['residents'] if p['status']=='evacuated' and not p.get('counted')]
        if ids:
            state = call('POST','/participant-actions',{'role':'居民代表','action':'resident_counted','message':'集合点逐人核验到场','resident_ids':ids})
        if state['simulation']['summary']['counted']==state['simulation']['summary']['total'] and all(t['status']=='completed' for t in state['tasks']):
            break
    else:
        raise AssertionError([(t['kind'], t['status'], t.get('blockers')) for t in state['tasks']])
    ended = call('PATCH','/state',{'action':'end'})
    final_run = next(r for r in call('GET','/agent/runs')['runs'] if r['id']==run['id'])
    assert final_run['status']=='completed'
    assert ended['score']['total_score'] >= 95
    print('CASE_RESULT='+json.dumps({'indoor':indoor,'score':ended['score']['total_score'],
        'seconds':ended['elapsed_seconds'],'summary':ended['simulation']['summary'],
        'candidate_count':len(run['candidates']),'agent':final_run['status']}))


def test_repaired_shed_complete_decision(exercise):
    client,headers,demo,old_root,_,_,clock,_,_ = exercise
    scene='/api/v1/scenes/'+demo['scene_id']
    old=client.get(old_root,headers=headers).json()
    params={**old['simulation']['world']['parameters'],'resident_count':18,'south_lane_status':'open','hydrant_status':'available','stair_width':1.2}
    assert client.patch(scene+'/charging-shed-parameters',headers=headers,json=params).is_success
    assert client.post(scene+'/publish',headers=headers).is_success
    created=client.post(scene+'/drills',headers=headers,json={'name':'修复后充电棚完整验收','training_mode':'teaching'}).json()
    root='/api/v1/drills/'+created['id']
    def tick(at):
        clock['t']=at
        with operations.SessionLocal() as db:
            operations.advance_engine(db, db.get(DrillSession,created['id']))
        return client.get(root,headers=headers).json()
    complete_case(client,headers,root,tick)


def test_repaired_kitchen_complete_decision(kitchen):
    client,headers,_,_,_,root,tick = kitchen
    complete_case(client,headers,root,tick,True)
