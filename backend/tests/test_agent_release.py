from types import SimpleNamespace
import pytest

from sqlalchemy import select

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillCommand
from app.services.agent_release import staged_release, suppression_blocker
from app.services.agent_task_graph import compile_graph
from app.services.agent_workflow import advance_run
from app.services.agent_schedule import release_schedule
from test_exercise_world import exercise


def test_serial_schedule_exposes_late_tasks_and_does_not_invent_outcomes():
    groups = [{'release_wave': n, 'building_id': str(n), 'resident_ids':[str(n)], 'exit':'north'}
              for n in (1, 2)]
    routes = {'north': {str(n): {'route_reachable':True, 'remaining_seconds':100} for n in (1, 2)}}
    robot = [{'building_id':str(n), 'planned_duration_seconds':10, 'arguments':{'command':'move'}} for n in (1, 2)]
    data = {'elapsed_seconds':20, 'events':[{'event_type':'robot.alarm_confirmed', 'elapsed_seconds':10}],
            'tasks':[{'id':'escort', 'title':'护送清点', 'kind':'escort', 'status':'pending', 'deadline_seconds':180}]}
    view = release_schedule(groups, routes, robot, {'duration_seconds':30}, data)
    assert view['estimated_completion_at'] == 262
    assert view['waves'][1]['release_at'] == 162
    assert view['deadline_risks'][0]['deadline_at'] == 190
    assert view['deadline_risks'][0]['estimated_ready_at'] == 262
    routes['north']['2']['route_reachable'] = False
    unknown = release_schedule(groups, routes, robot, {'duration_seconds':30}, data)
    assert not unknown['complete'] and unknown['estimated_completion_at'] is None
    assert unknown['deadline_risks'] == []
    assert release_schedule([], routes, robot, {}, data) is None


def test_building_waves_share_notification_dependencies_without_cycles():
    population = {'a': {'building_id': 'A'}, 'b': {'building_id': 'B'}}
    groups = [{'id': 'people', 'label': '居民分流 · 北门 · 2 人', 'action': 'evacuate',
               'exit': 'north', 'resident_ids': ['a', 'b']}]
    robot = [
        {'id':'move-b','label':'前往 B','kind':'robot.command','building_id':'B',
         'arguments':{'command':'move'},'resident_ids':[], 'depends_on':[]},
        {'id':'broadcast-b','label':'广播 B','kind':'robot.command','building_id':'B',
         'arguments':{'command':'broadcast'},'resident_ids':[], 'depends_on':['move-b']},
        {'id':'move-a','label':'前往 A','kind':'robot.command','building_id':'A',
         'arguments':{'command':'move'},'resident_ids':[], 'depends_on':['broadcast-b']},
        {'id':'broadcast-a','label':'广播 A','kind':'robot.command','building_id':'A',
         'arguments':{'command':'broadcast'},'resident_ids':[], 'depends_on':['move-a']},
    ]
    waves, commands = staged_release(groups, population, robot, 'spray')
    graph = compile_graph([{'id':'spray','label':'喷水','kind':'vehicle.command',
                            'arguments':{'command':'spray'},'resident_ids':[]}, *waves, *commands], 0)
    assert waves[0]['resident_ids'] == ['b']  # same order as route/battery preview
    assert 'broadcast-b' in waves[0]['depends_on']
    assert waves[0]['id'] in waves[1]['depends_on']
    move_a = next(s for s in commands if s['id']=='move-a')
    broadcast_a = next(s for s in commands if s['id']=='broadcast-a')
    assert move_a['depends_on'] == ['broadcast-b']
    assert waves[0]['id'] not in move_a['depends_on']
    assert waves[0]['id'] in broadcast_a['depends_on']
    assert 'move-a' in broadcast_a['depends_on']
    assert len(graph) == 8 and groups[0]['resident_ids'] == ['a','b']
    assert robot[-2]['depends_on'] == ['broadcast-b']


def test_release_rechecks_effective_water_not_just_old_spray_receipt():
    data = {'simulation': {'environment': {'east_hydrant':'available', 'water_suppression':True},
                           'vehicles': [{'id':'firetruck-1', 'service':{'action':'spray'}}]}}
    assert suppression_blocker(data) is None
    data['simulation']['environment']['east_hydrant'] = 'failed'
    assert '供水不可用' in suppression_blocker(data)
    data['simulation']['environment'].update(east_hydrant='available', water_suppression=False)
    assert '尚未生效' in suppression_blocker(data)
    data['simulation']['vehicles'][0]['service'] = None
    assert '未持续有效喷水' in suppression_blocker(data)


@pytest.mark.parametrize('fail_water', [True, False])
def test_two_building_decision_releases_first_wave_and_rechecks_water(exercise, fail_water):
    client, headers, _, root, _, _, clock, tick, start = exercise
    data = start()
    selected = {}
    for person in data['simulation']['residents']:
        if not person['vulnerable']:
            selected.setdefault(person['building_id'], person['id'])
    ids = list(selected.values())[:2]
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id':'building-wave-regression-0001', 'goal':'组织居民分流撤离',
        'resident_ids':ids, 'priority_assist':False})
    assert response.status_code == 201, response.text
    run = response.json()
    assert any(item['can_apply'] and not item.get('vehicle_support') for item in run['candidates'])
    candidate = next(item for item in run['candidates'] if item.get('vehicle_support'))
    assert candidate['can_apply'] and candidate['release_policy']['waves'] == 2
    waves = [step for step in candidate['groups'] if step.get('release_wave')]
    assert {pid for wave in waves for pid in wave['resident_ids']} == set(ids)
    approved = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers, json={
        'action':'approve','revision':1,'candidate_id':candidate['id']})
    assert approved.status_code == 200, approved.text
    assert all(step['status'] != 'completed' for step in approved.json()['steps']
               if step.get('kind') == 'vehicle.command' and step.get('arguments', {}).get('command') == 'spray')
    tick(clock['t'] + candidate['vehicle_support']['duration_seconds'] + 2)
    with operations.SessionLocal() as db:
        advance_run(db, db.get(AgentRun, run['id']), SimpleNamespace(username='admin'))
        commands = list(db.scalars(select(DrillCommand).where(DrillCommand.kind=='residents.assign')))
        assert len(commands) == 1
        assert commands[0].command_args['resident_ids'] == waves[0]['resident_ids']
        second = next(step for step in db.get(AgentRun,run['id']).steps if step.get('release_wave')==2)
        assert second['status'] == 'waiting'
    if not fail_water:
        for _ in range(16):
            current = tick(clock['t'] + 15)
            with operations.SessionLocal() as db:
                record = db.get(AgentRun,run['id'])
                advance_run(db, record, SimpleNamespace(username='admin'))
                assert record.status != 'needs_review', record.reason
            if all(person['status']=='evacuated' for person in current['simulation']['residents'] if person['id'] in ids):
                break
        assert all(person['status']=='evacuated' for person in current['simulation']['residents'] if person['id'] in ids)
        return
    failure = client.post(root+'/commands', headers=headers, json={
        'command_id':'release-water-failure-0001','kind':'event.inject',
        'arguments':{'event_type':'hydrant_failure','x':79,'y':47,'target':'东侧消火栓'}})
    assert failure.status_code == 200, failure.text
    with operations.SessionLocal() as db:
        advance_run(db, db.get(AgentRun, run['id']), SimpleNamespace(username='admin'))
        record = db.get(AgentRun,run['id'])
        assert record.status == 'needs_review' and '水源' in record.reason
        assert len(list(db.scalars(select(DrillCommand).where(DrillCommand.kind=='residents.assign')))) == 1
    replay = client.get(root+'/replay?at_seconds='+str(clock['t']), headers=headers)
    assert replay.status_code == 200
    assert replay.json()['simulation']['environment']['east_hydrant'] == 'failed'
