"""Notification gates must use actual receipts, not a planning assumption."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillSession
from app.services.agent_notifications import split_departures, notice_state
from app.services.agent_workflow import advance_run
from app.services.fire_environment import EnvironmentTimeline
from app.services.model_manifest import freeze_model_manifest, causal_environment
from app.services.training_archive import archive_drill
from test_community_training import community_run  # noqa: F401
from test_exercise_world import exercise  # noqa: F401


def report(client, headers, root, house):
    for action in ('household_notified', 'household_confirmed'):
        response = client.post(root+'/participant-actions', headers=headers, json={
            'role':'物业/网格员', 'action':action, 'channel':'phone', 'household_id':house,
            'message':'电话核对本户居民已经收到演练通知'})
        assert response.status_code == 200, response.text


def test_model_manifest_is_independent_of_resident_profile_and_preserves_history():
    regular = {'parameters':{'hydrant_status':'available'}}
    night = {**deepcopy(regular), 'community_training':{'version':4}}
    for world in (regular, night):
        freeze_model_manifest(world)
    events = [{'event_type':'participant.resource_ready', 'payload':{}, 'elapsed_seconds':5, 'sequence':1},
              {'event_type':'inject.hydrant_failure', 'payload':{}, 'elapsed_seconds':10, 'sequence':2}]
    assert EnvironmentTimeline(regular, events).at(30) == EnvironmentTimeline(night, events).at(30)
    assert regular['model_manifest']['residents'] != night['model_manifest']['residents']
    assert not causal_environment({'parameters':{}})
    assert causal_environment({'community_training':{'version':1}})
    with pytest.raises(ValueError):
        causal_environment({'model_manifest':{'environment':'unrecognized'}})


def test_split_retains_routes_and_requires_each_household_receipt():
    houses = [{'id':'b', 'label':'三层东户', 'resident_ids':['p2'], 'notification_state':'sent'}]
    data = {'simulation':{'world':{'model_manifest':{'orchestration':'notice_gates_v1'}},
                          'community':{'households':houses}}}
    groups = [{'id':'group', 'label':'南门 · 2 人', 'kind':'residents.assign',
               'resident_ids':['p2','p1'], 'exit':'south'}]
    routes = {'south':{'p1':{'route_edge_ids':['e1']}, 'p2':{'route_edge_ids':['e2']}}}
    original = deepcopy(groups)
    parts, gates = split_departures(groups, data, routes)
    assert groups == original and parts[0]['resident_ids'] == ['p1']
    assert parts[1]['route_edge_ids'] == ['e2']
    assert parts[1]['depends_on'] == [gates[0]['id']]
    assert notice_state(gates[0], data)['status'] == 'waiting'
    houses[0]['notification_state'] = 'confirmed'
    assert notice_state(gates[0], data)['status'] == 'completed'
    data['simulation']['world'] = {}
    assert split_departures(groups, data, routes) == (groups, [])


def test_plan_executes_ready_group_then_resumes_pending_household_without_replan(community_run):
    client, headers, root, data, tick, clock, _ = community_run
    ordinary = [p for p in data['simulation']['residents'] if not p['vulnerable']]
    first = ordinary[0]
    second = next(p for p in ordinary if p['household_id'] != first['household_id'])
    report(client, headers, root, first['household_id'])
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id':'notice-plan-regression-001', 'goal':'组织选中的居民分流撤离',
        'resident_ids':[first['id'], second['id']], 'priority_assist':False, 'pause_for_review':False})
    assert response.status_code == 201, response.text
    run = response.json()
    candidate = next(c for c in run['candidates'] if c['can_apply'] and not c.get('vehicle_support'))
    url = root+'/agent/runs/'+run['id']+'/actions'
    response = client.post(url, headers=headers, json={
        'action':'approve', 'revision':run['revision'], 'candidate_id':candidate['id']})
    assert response.status_code == 200, response.text
    def advance():
        with operations.SessionLocal() as db:
            advance_run(db, db.get(AgentRun, run['id']), SimpleNamespace(username='admin'))
        return next(r for r in client.get(root+'/agent/runs', headers=headers).json()['runs'] if r['id']==run['id'])
    waiting = advance()
    gate = next(s for s in waiting['steps'] if s['kind']=='community.notice')
    assert gate['status']=='waiting' and not gate['execution']['command_recorded']
    ready = next(s for s in waiting['steps'] if first['id'] in s.get('resident_ids', []))
    pending = next(s for s in waiting['steps'] if second['id'] in s.get('resident_ids', []))
    assert ready['execution']['command_recorded'] and not pending['execution']['command_recorded']
    report(client, headers, root, second['household_id'])
    resumed = advance()
    assert resumed['revision']==run['revision']
    assert next(s for s in resumed['steps'] if s['kind']=='community.notice')['status']=='completed'
    assert next(s for s in resumed['steps'] if second['id'] in s.get('resident_ids', []))['execution']['command_recorded']
    assert resumed['execution']['coordination']['notifications']['waiting']==0


def test_unconfirmed_escort_does_not_reserve_staff_needed_for_household_visit(community_run):
    client, headers, root, data, *_ = community_run
    person = next(p for p in data['simulation']['residents'] if p['vulnerable'])
    response = client.post(root+'/agent/runs', headers=headers, json={
        'request_id':'notice-escort-regression-001', 'goal':'优先护送选中的重点居民',
        'resident_ids':[person['id']], 'priority_assist':True, 'pause_for_review':False})
    assert response.status_code==201, response.text
    run = response.json()
    candidate = next(c for c in run['candidates'] if c['can_apply'] and not c.get('vehicle_support'))
    approved = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers, json={
        'action':'approve', 'revision':run['revision'], 'candidate_id':candidate['id']})
    assert approved.status_code==200, approved.text
    assert not approved.json()['scope']['resource_contract']['staff_ids']
    visit = client.post(root+'/participant-actions', headers=headers, json={
        'role':'物业/网格员', 'action':'household_visit', 'channel':'knock',
        'household_id':person['household_id'], 'message':'安排值守员到户核实并联系居民'})
    assert visit.status_code==200, visit.text
    assert any(v['household_id']==person['household_id'] for v in visit.json()['simulation']['community']['visits'])
    stopped = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers,
                          json={'action':'stop', 'revision':run['revision']})
    assert stopped.status_code==200, stopped.text
    report(client, headers, root, person['household_id'])
    with operations.SessionLocal() as db:
        advance_run(db, db.get(AgentRun, run['id']), SimpleNamespace(username='admin'))
    persisted = next(r for r in client.get(root+'/agent/runs', headers=headers).json()['runs'] if r['id']==run['id'])
    assert persisted['status']=='stopped'
    assert not any(s['execution']['command_recorded'] for s in persisted['steps'])


def test_archive_does_not_claim_verified_when_only_household_work_remains(community_run):
    _, _, root, data, *_ = community_run
    snapshot = deepcopy(data)
    for person in snapshot['simulation']['residents']:
        person.update(status='evacuated', counted=True, smoke_exposure=0)
    for task in snapshot['tasks']:
        task['status']='completed'
    snapshot['simulation']['fire']['intensity']=0
    snapshot['score']={'total':100}
    snapshot['simulation']['community']['visits']=[{'state':'at_door'}]
    with operations.SessionLocal() as db:
        drill = db.get(DrillSession, root.rsplit('/',1)[-1])
        drill.status='ended'
        record=archive_drill(db, drill, snapshot, 'admin')
        assert record.payload['experience_basis']['result_kind']=='incomplete'
        assert record.payload['unresolved']['household_visits_active']==1
        assert record.payload['unresolved']['households_unconfirmed']>0
        assert not any('均已核验' in finding for finding in record.payload['findings'])
        assert record.payload['model_manifest']==snapshot['simulation']['world']['model_manifest']
        original_hash=record.content_hash
        snapshot['simulation']['community']['summary']['confirmed']=999
        assert archive_drill(db, drill, snapshot, 'admin').content_hash==original_hash
