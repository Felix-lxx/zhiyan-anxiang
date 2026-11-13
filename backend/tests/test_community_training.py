from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.domain import Scene, DecisionPoint
from app.models.operations import DrillSession
from app.models.tasks import DecisionTask
from app.services.fire_environment import EnvironmentTimeline
from app.services.scenario_tasks import resolved_kind
from app.services.community_training import project_community
from test_exercise_world import exercise  # noqa: F401


@pytest.fixture
def community_run(exercise):
    client, headers, demo, old_root, _, _, clock, _, _ = exercise
    original = client.get(old_root, headers=headers).json()
    params = {**original['simulation']['world']['parameters'], 'resident_count':8,
              'community_profile':'night_shift', 'duty_staff_count':2, 'simulation_seed':37}
    changed = client.patch('/api/v1/scenes/'+demo['scene_id']+'/parameters', headers=headers, json=params)
    assert changed.status_code == 200, changed.text
    with operations.SessionLocal() as db:
        scene = db.get(Scene, demo['scene_id'])
        version = max(scene.versions, key=lambda v:v.version_number)
        point = db.scalar(select(DecisionPoint).where(DecisionPoint.scene_version_id==version.id))
        db.add(DecisionTask(decision_point_id=point.id, scene_version_id=version.id,
            kind='manual', title='检查门厅照明', target='门厅照明模拟核查', deadline_seconds=300))
        db.commit()
    assert client.post('/api/v1/scenes/'+demo['scene_id']+'/publish', headers=headers).status_code==200
    created = client.post('/api/v1/scenes/'+demo['scene_id']+'/drills', headers=headers,
                          json={'name':'社区夜班训练回归','training_mode':'teaching'})
    assert created.status_code==201, created.text
    root='/api/v1/drills/'+created.json()['id']

    def tick(t):
        clock['t']=t
        with operations.SessionLocal() as db:
            operations.advance_engine(db, db.get(DrillSession,created.json()['id']))
        return client.get(root,headers=headers).json()

    assert client.patch(root+'/state',headers=headers,json={'action':'start'}).status_code==200
    first=tick(0)
    at=first['robot']['task_queue'][0]['ends_at_seconds']
    for t in (at,at+2,at+4): data=tick(t)
    assert any(e['event_type']=='robot.alarm_confirmed' for e in data['events'])
    return client,headers,root,data,tick,clock,old_root


def test_profile_freezes_households_and_preserves_old_world(community_run):
    client,headers,root,data,_,_,old_root=community_run
    model=data['simulation']['community']
    assert model['source']=='simulation' and model['seed']==37
    assert len(data['simulation']['environment']['response_staff'])==2
    ids=[pid for h in model['households'] for pid in h['resident_ids']]
    assert len(ids)==len(set(ids))==8
    refreshed=client.get(root,headers=headers).json()
    assert refreshed['simulation']['world']['community_training']==data['simulation']['world']['community_training']
    assert not client.get(old_root,headers=headers).json()['simulation'].get('community')
    assert all(p.get('profile_label') for p in data['simulation']['residents'])


def test_household_receipt_requires_contact_and_is_replayed(community_run):
    client,headers,root,data,tick,clock,_=community_run
    house=next(h for h in data['simulation']['community']['households'] if h['direct_contact_required'])
    def report(action,channel='phone',household=house['id']):
        return client.post(root+'/participant-actions',headers=headers,json={
            'role':'物业/网格员','action':action,'channel':channel,'household_id':household,
            'message':'已联系本户居民，核对了演练通知内容'})
    assert report('household_confirmed').status_code==409
    assert report('household_notified',household='foreign-household').status_code==422
    assert report('household_notified','broadcast').status_code==200
    assert report('household_confirmed','broadcast').status_code==409
    assert report('household_notified').status_code==200
    done=report('household_confirmed')
    assert done.status_code==200,done.text
    assert done.json()['simulation']['community']['summary']['confirmed']==1
    assert all(p['release_at']>=10**9 for p in done.json()['simulation']['residents'] if p['household_id']==house['id'])
    dispatched=client.post(root+'/residents',headers=headers,json={'resident_ids':house['resident_ids'], 'exit':'south','action':'evacuate'})
    assert dispatched.status_code==200,dispatched.text
    after=tick(clock['t']+60)
    assert all(p['release_at']<10**9 for p in after['simulation']['residents'] if p['household_id']==house['id'])
    assert all(p['release_at']>=10**9 for p in after['simulation']['residents'] if p['household_id']!=house['id'])
    replay=client.get(root+'/replay?at_seconds=0',headers=headers).json()
    assert replay['simulation']['community']['summary']['confirmed']==0


def test_two_staff_cannot_accept_three_jobs_and_release_is_real(community_run):
    client,headers,root,data,_,_,_=community_run
    jobs=[t for t in data['tasks'] if t['responsible_role']=='物业/网格员']
    assert len(jobs)>=3
    def act(job,action):
        return client.post(root+'/tasks/'+job['id']+'/actions',headers=headers,
                           json={'action':action,'evidence':'撤回当前接收并释放值守岗位'})
    assert act(jobs[0],'accept').status_code==200
    second=act(jobs[1],'accept')
    assert second.status_code==200,second.text
    assert sum(s['state']=='task' for s in second.json()['simulation']['environment']['response_staff'])==2
    assert act(jobs[2],'accept').status_code==409
    person=next(p for p in data['simulation']['residents'] if p['vulnerable'])
    for action in ('household_notified', 'household_confirmed'):
        response=client.post(root+'/participant-actions',headers=headers,json={'role':'物业/网格员',
            'action':action,'household_id':person['household_id'],'channel':'phone','message':'电话核对本户居民已经收到通知'})
        assert response.status_code==200,response.text
    conflict=client.post(root+'/residents',headers=headers,json={'resident_ids':[person['id']],
        'exit':'south','action':'priority_assist'})
    assert conflict.status_code==409 and '值守' in conflict.text
    proposal=client.post(root+'/agent/runs',headers=headers,json={
        'request_id':'occupied-night-staff-plan-001','goal':'护送选中的重点居民到集合点',
        'resident_ids':[person['id']],'priority_assist':True,'pause_for_review':False})
    assert proposal.status_code==201,proposal.text
    assert not any(c['can_apply'] for c in proposal.json()['candidates'])
    released=act(jobs[0],'release')
    assert released.status_code==200,released.text
    assert next(t for t in released.json()['tasks'] if t['id']==jobs[0]['id'])['status']=='pending'
    assert act(jobs[2],'accept').status_code==200


def test_typed_task_name_does_not_change_semantics():
    assert resolved_kind(SimpleNamespace(kind='gas_off',title='关闭北侧设施'))=='gas_off'
    assert resolved_kind(SimpleNamespace(kind='manual',title='切断电源'))=='manual'
    assert resolved_kind(SimpleNamespace(kind=None,title='切断充电棚电源'))=='power_off'


def test_knock_receipt_requires_onsite_responsibility():
    from fastapi import HTTPException
    from app.services.household_visits import check_knock
    community = {'version':2, 'visits':[{'household_id':'house-a', 'state':'blocked', 'participant_id':'owner'}]}
    payload = SimpleNamespace(channel='knock', household_id='house-a')
    with pytest.raises(HTTPException) as early:
        check_knock(community, payload, {'participant_id':'owner'})
    assert early.value.status_code == 409
    community['visits'][0]['state'] = 'at_door'
    with pytest.raises(HTTPException) as other:
        check_knock(community, payload, {'participant_id':'other'})
    assert other.value.status_code == 403
    check_knock(community, payload, {'participant_id':'owner'})


def test_broadcast_coverage_respects_scope_without_confirming_receipt():
    houses = [{'id': 'house-a', 'building_id': 'a', 'resident_ids': []},
              {'id': 'house-b', 'building_id': 'b', 'resident_ids': []}]
    world = {'community_training': {'households': houses}}
    event = SimpleNamespace(event_type='robot.broadcast_completed',
                            payload={'building_id': 'a'}, elapsed_seconds=12)
    scoped = project_community(world, [event], [])
    assert [h['notification_state'] for h in scoped['households']] == ['sent', 'unnotified']
    event.payload = {}
    community_wide = project_community(world, [event], [])
    assert all(h['notification_state'] == 'sent' for h in community_wide['households'])
    assert community_wide['summary']['confirmed'] == 0


def test_visit_walks_to_door_and_holds_staff_until_receipt(community_run):
    client, headers, root, data, tick, clock, _ = community_run
    house = min(data['simulation']['community']['households'], key=lambda h:h['floor'])
    def report(action):
        return client.post(root+'/participant-actions', headers=headers, json={
            'role':'物业/网格员', 'action':action, 'channel':'knock', 'household_id':house['id'],
            'message':'前往本户核查通知，记录本次联系结果'})
    assert report('household_notified').status_code == 409
    accepted = report('household_visit')
    assert accepted.status_code == 200, accepted.text
    visit = accepted.json()['simulation']['community']['visits'][0]
    assert visit['state'] == 'approaching'
    assert report('household_visit').status_code == 409
    initial = (visit['x'], visit['y'], visit['height'])
    moved = tick(clock['t']+3)['simulation']['community']['visits'][0]
    assert (moved['x'], moved['y'], moved['height']) != initial
    assert report('household_notified').status_code == 409
    for _ in range(10):
        data = tick(clock['t']+30)
        visit = data['simulation']['community']['visits'][0]
        if visit['state'] == 'at_door': break
    assert visit['state'] == 'at_door', visit['behavior']
    assert not any(p['assisted'] for p in data['simulation']['residents'])
    assert data['simulation']['community']['summary']['confirmed'] == 0
    assert any(s.get('activity')=='household_visit' for s in data['simulation']['environment']['response_staff'])
    assert report('household_notified').status_code == 200
    done = report('household_confirmed')
    assert done.status_code == 200, done.text
    assert done.json()['simulation']['community']['visits'][0]['state'] == 'completed'
    assert all(s['state']=='available' for s in done.json()['simulation']['environment']['response_staff'])
    assert all(p['release_at']>=10**9 for p in done.json()['simulation']['residents'])


def test_visiting_staff_cannot_double_book_and_cancel_keeps_position(community_run):
    client, headers, root, data, tick, clock, _ = community_run
    houses = data['simulation']['community']['households'][:3]
    def visit(house, action='household_visit'):
        return client.post(root+'/participant-actions', headers=headers, json={
            'role':'物业/网格员','action':action,'household_id':house['id'],
            'message':'安排到户核查，调整时保留当前位置'})
    assert visit(houses[0]).status_code == 200
    assert visit(houses[1]).status_code == 200
    assert visit(houses[2]).status_code == 409
    before = tick(clock['t']+3)['simulation']['community']['visits'][0]
    cancelled = visit(houses[0], 'household_visit_cancel')
    assert cancelled.status_code == 200, cancelled.text
    same = cancelled.json()['simulation']['community']['visits'][0]
    assert (same['x'], same['y'], same['height']) == (before['x'], before['y'], before['height'])
    for _ in range(10):
        after = tick(clock['t']+10)
        same = after['simulation']['community']['visits'][0]
        if same['state']=='completed': break
    assert same['state']=='completed' and same['cancelling']
    assert after['simulation']['community']['summary']['confirmed'] == 0
    assert visit(houses[2]).status_code == 200


def test_resource_readiness_and_water_failure_are_not_suppression():
    world={'parameters':{'hydrant_status':'available'},'community_training':{'version':1}}
    base=EnvironmentTimeline(world,[]).at(30)[0]
    events=[{'elapsed_seconds':3,'sequence':1,'event_type':'inject.hydrant_failure','payload':{}},
            {'elapsed_seconds':5,'sequence':2,'event_type':'participant.resource_ready','payload':{}}]
    fire,environment=EnvironmentTimeline(world,events).at(30)
    assert fire==base and environment['east_hydrant']=='failed' and not environment['water_suppression']
    wrong_energy=events+[{'elapsed_seconds':6,'sequence':3,'event_type':'task.completed','payload':{'kind':'gas_off'}}]
    assert EnvironmentTimeline(world,wrong_energy).at(30)[0]==base
    isolated=events+[{'elapsed_seconds':6,'sequence':3,'event_type':'task.completed','payload':{'kind':'power_off'}}]
    assert 0<EnvironmentTimeline(world,isolated).at(30)[0]['intensity']<base['intensity']
