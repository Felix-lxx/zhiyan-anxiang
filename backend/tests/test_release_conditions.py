from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.api.routes import operations
from app.models.agent import AgentRun
from app.services.agent_release import staged_release
from app.services.agent_schedule import release_schedule
from app.services.agent_task_graph import compile_graph, validate_graph
from app.services.agent_workflow import advance_run
from app.services.release_conditions import check_release
from test_community_training import community_run  # noqa: F401
from test_exercise_world import exercise  # noqa: F401


@pytest.fixture
def gate():
    prior = {'id':'first', 'status':'executing', 'command_id':'first-command'}
    step = {'id':'second', 'kind':'residents.assign', 'action':'evacuate',
            'resident_ids':['b'], 'route_edge_ids':['lane'], 'release_after':['first'],
            'release_gate':{'mode':'shared_corridor','density_limit':55}, 'status':'waiting'}
    data = {'elapsed_seconds':42, 'commands':[], 'simulation':{
        'residents':[{'id':'a','status':'moving'}, {'id':'b','status':'waiting'}],
        'spatial_network':{'edges':[{'id':'lane','name':'门厅通道','density_percent':20,'status':'open'}]},
        'community':{'households':[{'resident_ids':['b'],'notification_state':'confirmed'}]},
        'environment':{'response_staff':[{'id':'staff','state':'available'}]}}}
    return step, data, [prior, step]


def test_release_uses_accepted_departure_instead_of_assembly_arrival(gate):
    step, data, steps = gate
    before = deepcopy(data)
    assert check_release(step, data, steps)['ready']
    assert data == before  # projection and executor checks cannot advance simulation
    steps[0]['status'] = 'waiting'
    assert not check_release(step, data, steps)['ready']
    data['commands'] = [{'id':'first-command','status':'accepted'}]
    assert check_release(step, data, steps)['ready']


@pytest.mark.parametrize('field,value,kind,state', [
    ('density_percent',55,'capacity','waiting'),
    ('reserved_by_vehicle','firetruck-1','traffic','waiting'),
    ('status','blocked','route','blocked'),
    ('geometry_blocked',True,'route','blocked'),
])
def test_real_passage_constraints_explain_wait_and_recover(gate, field, value, kind, state):
    step, data, steps = gate
    edge = data['simulation']['spatial_network']['edges'][0]
    previous = deepcopy(edge)
    edge[field] = value
    blocked = check_release(step, data, steps)
    assert blocked['state'] == state and not blocked['ready']
    assert next(c for c in blocked['checks'] if c['kind']==kind)['edge_id'] == 'lane'
    edge.clear(); edge.update(previous)
    assert check_release(step, data, steps)['ready']


def test_missing_route_requires_revision_and_notification_never_blocks_broadcast(gate):
    step, data, steps = gate
    house = data['simulation']['community']['households'][0]
    house['notification_state'] = 'sent'
    assert not check_release(step, data, steps)['ready']
    step['kind'] = 'robot.command'
    step['gate_resident_ids'] = ['b']
    assert check_release(step, data, steps)['ready']  # coverage can help solicit a receipt
    step['route_edge_ids'] = ['deleted-lane']
    assert check_release(step, data, steps)['state'] == 'blocked'


def test_staff_and_completion_dependencies_are_independent_gates(gate):
    step, data, steps = gate
    step['action'] = 'priority_assist'
    data['simulation']['environment']['response_staff'][0]['state'] = 'task'
    view = check_release(step, data, steps)
    assert not view['ready'] and '接应岗位' in [c['label'] for c in view['checks'] if not c['passed']]
    data['simulation']['helpers'] = [{'resident_id':'b','state':'escorting'}]
    assert check_release(step, data, steps)['ready']
    step['depends_on'] = ['first']
    assert not check_release(step, data, steps)['ready']  # accepted != completed
    steps[0]['status'] = 'completed'
    assert check_release(step, data, steps)['ready']


def test_water_failure_waits_for_deployment_then_requires_revision(gate):
    step, data, steps = gate
    step.update(release_condition='active_suppression', depends_on=['first'])
    data['simulation']['environment']['east_hydrant'] = 'failed'
    view = check_release(step, data, steps)
    assert view['state'] == 'waiting'
    steps[0]['status'] = 'completed'
    view = check_release(step, data, steps)
    assert view['state'] == 'blocked' and '供水不可用' in view['reason']
    data['simulation']['fire'] = {'intensity':0,'smoke_radius':0}
    assert check_release(step, data, steps)['ready']


def test_conditional_graph_scopes_routes_and_preserves_hard_robot_dependencies():
    population = {'a':{'building_id':'A'}, 'b':{'building_id':'B'}}
    groups = [{'id':'people','label':'居民分流','resident_ids':['a','b'],'exit':'north','action':'evacuate'}]
    resources = [
        {'id':'move-a','kind':'robot.command','building_id':'A','arguments':{'command':'move'},'depends_on':[]},
        {'id':'say-a','kind':'robot.command','building_id':'A','arguments':{'command':'broadcast'},'depends_on':['move-a']},
        {'id':'move-b','kind':'robot.command','building_id':'B','arguments':{'command':'move'},'depends_on':['say-a']},
        {'id':'say-b','kind':'robot.command','building_id':'B','arguments':{'command':'broadcast'},'depends_on':['move-b']},
    ]
    for r in resources: r.update(label=r['id'], resident_ids=[])
    routes = {'north':{'a':{'route_edge_ids':['A-lane']},'b':{'route_edge_ids':['B-lane']}}}
    waves, robot = staged_release(groups,population,resources,'spray',
        release_policy={'mode':'shared_corridor','density_limit':55},routes=routes)
    first, second = waves
    assert first['route_edge_ids'] == ['A-lane'] and second['route_edge_ids'] == ['B-lane']
    assert first['id'] not in second['depends_on'] and second['release_after'] == [first['id']]
    assert next(s for s in robot if s['id']=='move-b')['depends_on'] == ['say-a']
    assert first['id'] not in next(s for s in robot if s['id']=='say-b')['depends_on']
    compile_graph([{'id':'spray','label':'喷水','kind':'vehicle.command','arguments':{},'resident_ids':[]}, *waves,*robot],0)
    view = release_schedule(waves,routes,robot,{}, {'elapsed_seconds':0})
    assert not view['complete'] and view['estimated_completion_at'] is None
    assert all(w['release_at'] is None for w in view['waves'])


@pytest.mark.parametrize('steps', [
    [{'id':'a','release_after':['missing']}],
    [{'id':'a','release_after':['b']},{'id':'b','depends_on':['a']}],
])
def test_acceptance_dependencies_are_validated_for_missing_nodes_and_cycles(steps):
    with pytest.raises(ValueError): validate_graph(steps)


def test_new_world_freezes_policy_and_releases_before_previous_assembly(community_run):
    client,headers,root,data,tick,clock,_ = community_run
    policy = data['simulation']['world']['community_training']['release_policy']
    assert policy == {'mode':'shared_corridor','density_limit':55,'version':1}
    selected = {}
    for p in data['simulation']['residents']:
        if not p['vulnerable']: selected.setdefault(p['building_id'],p['id'])
    ids = list(selected.values())[:2]
    assert len(ids)==2
    for house in data['simulation']['community']['households']:
        if not set(house['resident_ids']).intersection(ids): continue
        for action in ('household_notified','household_confirmed'):
            reply = client.post(root+'/participant-actions',headers=headers,json={
                'role':'物业/网格员','action':action,'channel':'phone','household_id':house['id'],
                'message':'电话核对本户居民已经收到通知'})
            assert reply.status_code==200, reply.text
    response = client.post(root+'/agent/runs',headers=headers,json={
        'request_id':'conditional-release-integration','goal':'组织居民分流撤离',
        'resident_ids':ids,'priority_assist':False})
    assert response.status_code==201, response.text
    run = response.json()
    candidate = next(c for c in run['candidates'] if c.get('vehicle_support'))
    assert candidate['release_policy']['mode']=='conditional_waves'
    assert candidate['can_apply'], candidate['reason']
    approved = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers,json={
        'action':'approve','revision':run['revision'],'candidate_id':candidate['id']})
    assert approved.status_code==200, approved.text
    first_wave = next(g for g in candidate['groups'] if g.get('release_wave')==1)
    second_wave = next(g for g in candidate['groups'] if g.get('release_wave')==2)
    tick(clock['t']+candidate['vehicle_support']['duration_seconds']+2)
    for _ in range(8):
        data = tick(clock['t']+5)
        with operations.SessionLocal() as db:
            record = db.get(AgentRun,run['id'])
            advance_run(db,record,SimpleNamespace(username='admin'))
        result = client.get(root+'/agent/runs',headers=headers)
        assert result.status_code==200, result.text
        live = next(r for r in result.json()['runs'] if r['id']==run['id'])
        second = next(s for s in live['steps'] if s['id']==second_wave['id'])
        if second['status'] in {'accepted','executing','completed'}:
            first = next(s for s in live['steps'] if s['id']==first_wave['id'])
            assert first['status']!='completed'
            break
    else:
        pytest.fail('Second wave did not release while the first was still en route: '+live['reason'])
    restored = client.get(root,headers=headers).json()
    assert restored['simulation']['world']['community_training']['release_policy']==policy
