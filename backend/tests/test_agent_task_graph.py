from copy import deepcopy
from types import SimpleNamespace
import pytest
from sqlalchemy import select, delete
from app.api.routes import operations
from app.models.agent import AgentRun, AgentResourceClaim
from app.models.operations import DrillCommand, DrillEvent
from app.models.tasks import DecisionTask
from app.services.agent_workflow import advance_run
from app.services.agent_task_graph import compile_graph, graph_view, validate_graph
from test_exercise_world import exercise
from test_agent_workflow import proposal


def test_dependency_validation_and_escort_waves():
    graph=compile_graph([{'id':'first','label':'第一批','resident_ids':['a'],'action':'priority_assist'},
                         {'id':'parallel','label':'分流','resident_ids':['b'],'action':'evacuate'},
                         {'id':'second','label':'第二批','resident_ids':['c'],'action':'priority_assist'}],0)
    assert graph[1]['depends_on']==[] and graph[2]['depends_on']==['first']
    graph[0]['depends_on']=['second']
    with pytest.raises(ValueError,match='循环'): validate_graph(graph)


def test_split_floor_escorts_use_real_parallel_capacity():
    groups = [{'id': str(i), 'label': '分层护送', 'resident_ids': [str(i)], 'action': 'priority_assist'} for i in range(3)]
    graph = compile_graph(groups, 0, escort_capacity=2)
    assert graph[0]['depends_on'] == graph[1]['depends_on'] == []
    assert graph[2]['depends_on'] == ['0']
    assert all('depends_on' not in group for group in groups)


def test_case_responsibilities_share_graph_without_synthetic_completion():
    steps = compile_graph([
        {'id':'escort-floor-3','label':'重点护送 · 3层','resident_ids':['a'],'action':'priority_assist'},
        {'id':'close-room','label':'关闭起火房门','resident_ids':[], 'kind':'indoor.door.set'},
        {'id':'broadcast','label':'机器人入口广播','resident_ids':[], 'kind':'robot.command',
         'arguments':{'command':'broadcast'}},
    ], 0)
    tasks = [
        {'id':'gas','kind':'gas_off','title':'切断燃气','status':'verifying','responsible_role':'物业值守员',
         'remaining_seconds':12,'blockers':['现场操作尚未完成'],'verification_ready':False},
        {'id':'door','kind':'containment','title':'关闭房门','status':'verifying','responsible_role':'楼栋网格员',
         'remaining_seconds':8,'blockers':[],'verification_ready':True},
        {'id':'notice','kind':'broadcast','title':'入口广播','status':'executing','responsible_role':'机器人操作员',
         'remaining_seconds':30,'blockers':['等待机器人广播'],'verification_ready':False},
        {'id':'escort','kind':'escort','title':'重点护送','status':'pending','responsible_role':'社区值守员',
         'remaining_seconds':40,'blockers':[],'verification_ready':False},
    ]
    data = {'simulation': {'residents': [{'id':'a','status':'moving','counted':False}]}, 'tasks': tasks}
    view = graph_view(steps, data, ['a'])
    projected = {task['kind']: task for task in view['case_tasks']}
    assert view['version'] == 2
    assert projected['gas_off']['depends_on'] == []
    assert projected['containment']['depends_on'] == ['close-room']
    assert projected['broadcast']['depends_on'] == ['broadcast']
    assert projected['escort']['depends_on'] == ['escort-floor-3']
    assert projected['containment']['next_required_action'] == '现场条件已满足，请提交核验证据'
    assert all(task['automation'] == 'human_verified' for task in projected.values())
    assert view['human_gate']['depends_on'] == ['escort-floor-3']


def test_resource_waiting_persistent_recovery_and_manual_takeover(exercise):
    client,headers,demo,root,_,_,clock,tick,start=exercise
    with operations.SessionLocal() as db:
        event=db.scalar(select(DrillEvent).where(DrillEvent.drill_session_id==demo['drill_id'],DrillEvent.event_type=='drill.created'))
        payload=deepcopy(event.payload);payload['world']['response_staff']=payload['world']['response_staff'][:1]
        event.payload=payload;db.commit()
    state=start(); ids=[p['id'] for p in state['simulation']['residents'] if p['vulnerable']][:2]
    first=proposal(client,headers,root,ids[:1],request='resource-first-001')
    second=proposal(client,headers,root,ids[1:],request='resource-second-001')
    def approve(run):
        result=client.post(root+'/agent/runs/'+run['id']+'/actions',headers=headers,json={'action':'approve','revision':1,'candidate_id':next(c['id'] for c in run['candidates'] if c['can_apply'] and not c.get('vehicle_support'))})
        assert result.status_code==200,result.text
        return result.json()
    begun=approve(first); waiting=approve(second)
    assert begun['resources']['items'][0]['state']=='owned'
    assert waiting['status']=='waiting' and '值守资源' in waiting['reason']
    with operations.SessionLocal() as db:
        count=len(list(db.scalars(select(DrillCommand.command_id))))
        advance_run(db,db.get(AgentRun,first['id']),SimpleNamespace(username='admin'))
        assert len(list(db.scalars(select(DrillCommand.command_id))))==count
        staff=list(db.scalars(select(AgentResourceClaim).where(AgentResourceClaim.resource_key.like('staff:%'),AgentResourceClaim.run_id.is_not(None))))
        assert len(staff)==1 and staff[0].run_id==first['id']
    manual=client.post(root+'/residents',headers=headers,json={'resident_ids':ids[:1],'exit':'north','action':'evacuate'})
    assert manual.status_code==200,manual.text
    with operations.SessionLocal() as db:
        assert db.get(AgentRun,first['id']).status=='taken_over'
        assert not list(db.scalars(select(AgentResourceClaim).where(AgentResourceClaim.run_id==first['id'])))
        advance_run(db,db.get(AgentRun,second['id']),SimpleNamespace(username='admin'))
        resumed = db.get(AgentRun, second['id'])
        assert resumed.status == 'waiting', resumed.reason  # physical helper has not finished


def test_missing_task_repair_creates_draft_and_preserves_old_world(exercise):
    client,headers,demo,root,*_=exercise
    before=client.get(root,headers=headers).json()['simulation']['world']
    with operations.SessionLocal() as db:
        db.execute(delete(DecisionTask).where(DecisionTask.scene_version_id==before['scene_version_id']));db.commit()
    scene='/api/v1/scenes/'+demo['scene_id']
    validation=client.post(scene+'/validate',headers=headers).json()
    assert not validation['passed'] and any(i['key']=='tasks' for i in validation['issue_details'])
    assert client.post(scene+'/drills',headers=headers,json={'name':'不允许空任务'}).status_code==422
    fixed=client.post(scene+'/repair-tasks',headers=headers)
    assert fixed.status_code==200,fixed.text
    assert fixed.json()['status']=='draft'
    assert client.post(scene+'/validate',headers=headers).json()['passed']
    assert client.get(root,headers=headers).json()['simulation']['world']==before


def test_stopped_plan_does_not_release_a_vehicle_still_moving(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    ids = [person['id'] for person in data['simulation']['residents'] if not person['vulnerable']][:2]
    plans = []
    for index, resident_id in enumerate(ids):
        response = client.post(root+'/agent/runs', headers=headers, json={
            'request_id':f'physical-vehicle-wait-{index:04}',
            'goal':'先派消防车到场喷水压制，再疏散居民',
            'resident_ids':[resident_id], 'priority_assist':False})
        assert response.status_code == 201, response.text
        plans.append(response.json())
    def approve(run):
        candidate = next(item for item in run['candidates'] if item.get('vehicle_support'))
        response = client.post(root+'/agent/runs/'+run['id']+'/actions', headers=headers,
            json={'action':'approve','revision':1,'candidate_id':candidate['id']})
        assert response.status_code == 200, response.text
        return response.json()
    approve(plans[0])
    stopped = client.post(root+'/agent/runs/'+plans[0]['id']+'/actions', headers=headers,
        json={'action':'stop','revision':1})
    assert stopped.status_code == 200, stopped.text
    waiting = approve(plans[1])
    assert waiting['status'] == 'waiting' and '消防车' in waiting['reason']
    with operations.SessionLocal() as db:
        dispatches = [command for command in db.scalars(select(DrillCommand))
                      if command.kind == 'vehicle.command' and command.command_args.get('command') == 'dispatch']
        assert len(dispatches) == 1
