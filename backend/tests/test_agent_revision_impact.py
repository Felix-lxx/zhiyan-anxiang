from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillCommand
from app.services.agent_impact import impact_view
from test_agent_workflow import proposal
from test_exercise_world import exercise


@pytest.mark.parametrize('counted,tasks_completed,expected', [
    (True, False, 'awaiting_rollcall'),
    (False, True, 'awaiting_rollcall'),
    (True, True, 'completed'),
])
def test_arrived_replan_requires_both_responsibility_evidence_and_rollcall(
        monkeypatch, counted, tasks_completed, expected):
    from app.services import agent_claims, agent_revision, agent_workflow

    monkeypatch.setattr(agent_workflow, 'relevant_changes', lambda *args: [])
    monkeypatch.setattr(agent_workflow, 'note', lambda *args: None)
    released = []
    monkeypatch.setattr(agent_claims, 'release', lambda session, run_id: released.append(run_id))
    session = SimpleNamespace(commit=lambda: None)
    run = SimpleNamespace(id='plan', scope={
        'resident_ids': ['r1'], 'priority_assist': False, 'include_case_tasks': True,
    }, observed_sequence=5)
    data = {'elapsed_seconds': 70, 'simulation': {'residents': [
        {'id': 'r1', 'status': 'evacuated', 'counted': counted},
    ]}, 'tasks': [{'status': 'completed' if tasks_completed else 'verifying'}]}

    agent_revision.replan(session, None, run, data, None, None)

    assert run.status == expected
    assert released == ['plan']


def test_impact_keeps_individual_routes_and_propagates_robot_dependencies():
    people=[{'id':'p1','label':'居民一','status':'moving','route_reachable':True},
            {'id':'p2','label':'居民二','status':'moving','route_reachable':True}]
    run=SimpleNamespace(scope={'resident_ids':['p1','p2'],'robot_broadcast':True},
        drill_session_id='d',observed_sequence=10,selected_candidate='c',evidence=[],
        candidates=[{'id':'c','assignments':[{'id':'p1','route_edge_ids':['e1']},{'id':'p2','route_edge_ids':['e2']}],
                     'robot_support':{'route_edge_ids':['e1']}}],steps=[
            {'id':'residents','label':'居民分流','status':'executing','command_id':'resident-command',
             'resident_ids':['p1','p2'],'route_edge_ids':['e1','e2']},
            {'id':'robot-move','label':'机器人前往楼门','status':'executing','kind':'robot.command',
             'resident_ids':[],'command_id':'robot-command','route_edge_ids':['e1']},
            {'id':'broadcast','label':'到位广播','status':'waiting','kind':'robot.command','resident_ids':[],
             'command_id':'broadcast-command','depends_on':['robot-move']}])
    event=SimpleNamespace(id='event-11',sequence=11,event_type='inject.channel_blocked',elapsed_seconds=5,
        payload={'blocked_edge_id':'e1'},message='北侧通道封锁')
    class Session:
        def scalars(self,statement):
            return [] if 'drill_commands' in str(statement) else [event]
    data={'elapsed_seconds':5,'latest_event_sequence':11,'simulation':{'residents':people,'spatial_network':{'edges':[{'id':'e1','name':'北侧通道'}]}}}
    result=impact_view(Session(),run,data)
    assert result['affected_count']==1
    assert result['residents'][0]['id']=='p1'
    assert result['robot_affected']
    assert result['step_count']==3
    assert next(s for s in result['steps'] if s['id']=='broadcast')['direct'] is False


def test_real_replan_refreshes_knowledge_and_retains_commands_and_position(exercise):
    client,headers,_,root,_,_,_,_,start=exercise
    data=start()
    ids=[p['id'] for p in data['simulation']['residents'] if not p['vulnerable']][:2]
    run=proposal(client,headers,root,ids,'impact-revision-0001')
    selected=next(c for c in run['candidates'] if c['can_apply'])
    path=root+'/agent/runs/'+run['id']+'/actions'
    assert client.post(path,headers=headers,json={'action':'approve','revision':1,'candidate_id':selected['id']}).status_code==200
    with operations.SessionLocal() as db:
        current=db.get(AgentRun,run['id'])
        commands=list(db.scalars(select(DrillCommand.command_id)))
        original_knowledge=deepcopy(current.scope['knowledge'])
    reviewed=client.post(path,headers=headers,json={'action':'review','revision':1})
    assert reviewed.status_code==200
    assert client.patch(root+'/state',headers=headers,json={'action':'pause'}).status_code==200
    before=client.get(root,headers=headers).json()['simulation']['residents']
    revised=client.post(path,headers=headers,json={'action':'replan','revision':reviewed.json()['revision'],
        'objective':'low_exposure','forbidden_exits':['north']})
    assert revised.status_code==200,revised.text
    value=revised.json()
    assert value['scope']['objective']=='low_exposure'
    assert value['scope']['forbidden_exits']==['north']
    assert value['knowledge']['retrieval_id']!=original_knowledge['retrieval_id']
    assert value['revision_context']['baseline']=='approved'
    assert value['revision_context']['from_revision']==1
    assert value['revision_context']['new_forbidden_exits']==['north']
    assert all(p['exit']=='south' for c in value['candidates'] for p in c['assignments'])
    after=client.get(root,headers=headers).json()['simulation']['residents']
    assert [(p['id'],p['x'],p['y'],p['height'],p['smoke_exposure']) for p in before]==[(p['id'],p['x'],p['y'],p['height'],p['smoke_exposure']) for p in after]
    with operations.SessionLocal() as db:
        current=db.get(AgentRun,run['id'])
        assert list(db.scalars(select(DrillCommand.command_id)))==commands
        assert current.evidence[-1]['scope']['knowledge']==original_knowledge
    invalid=client.post(path,headers=headers,json={'action':'approve','revision':value['revision'],
        'candidate_id':value['candidates'][0]['id'],'forbidden_exits':[]})
    assert invalid.status_code==422
    reply=client.post(root+'/assistant/chat',headers=headers,json={'message':'这个计划为什么要重新比较？','use_model':False})
    assert reply.status_code==200,reply.text
    assert any(source['title']=='本场目标计划与执行' for source in reply.json()['sources'])
    assert any(action.get('plan_id')==run['id'] for action in reply.json()['actions'])
    historical=client.post(root+'/assistant/chat',headers=headers,json={'message':'这个计划为什么要重新比较？','at_seconds':0,'use_model':False})
    assert historical.status_code==200,historical.text
    assert not any(source['title']=='本场目标计划与执行' for source in historical.json()['sources'])


def test_walking_forward_is_not_reported_as_a_route_decision_change():
    from app.services.agent_impact import revision_difference
    run=SimpleNamespace(revision=1,selected_candidate='old',scope={},steps=[],candidates=[{'id':'old','assignments':[
        {'id':'p1','exit':'north','route_edge_ids':['walked','remaining']}]}])
    data={'elapsed_seconds':5,'simulation':{'residents':[{'id':'p1','node_id':'b'}],
        'spatial_network':{'edges':[{'id':'walked','start_node_id':'a','end_node_id':'b'},
                                   {'id':'remaining','start_node_id':'b','end_node_id':'c'}]}}}
    new=[{'id':'new','assignments':[{'id':'p1','exit':'north','route_edge_ids':['remaining']}]}]
    assert revision_difference(run,data,new,{})['candidates'][0]['changed_count']==0


def test_unrelated_door_change_does_not_invalidate_a_plan(exercise):
    client,headers,demo,root,_,_,_,_,start=exercise
    data=start()
    run=proposal(client,headers,root,[data['simulation']['residents'][0]['id']],'unrelated-door-001')
    from app.models.operations import DrillSession
    from app.services.agent_workflow import relevant_changes
    with operations.SessionLocal() as db:
        drill=db.get(DrillSession,demo['drill_id'])
        operations.append_event(db,drill,'indoor.door_changed','测试员','无关房门变化',{'door_id':'unrelated-door','room_id':'other-room','state':'closed'})
        db.commit()
        record=db.get(AgentRun,run['id'])
        assert not relevant_changes(db,record,record.observed_sequence)


@pytest.mark.parametrize('use_model', [False, True])
def test_rejected_goal_does_not_leave_the_drill_paused(exercise, use_model):
    client,headers,_,root,_,_,_,_,start=exercise
    start()
    response=client.post(root+'/agent/runs',headers=headers,json={'request_id':'no-floor-scope-001',
        'goal':'疏散目标居民','floors':[99],'pause_for_review':True,'use_model':use_model})
    assert response.status_code==409
    assert client.get(root,headers=headers).json()['status']=='running'


def test_passed_door_does_not_pause_remaining_actions_but_future_doors_still_do(exercise):
    client,headers,demo,root,_,_,_,_,start=exercise
    data=start();pid=data['simulation']['residents'][0]['id']
    plan=proposal(client,headers,root,[pid],'passed-door-guard-001')
    from app.models.operations import DrillSession
    from app.services.agent_workflow import relevant_changes
    with operations.SessionLocal() as db:
        run=db.get(AgentRun,plan['id'])
        run.selected_candidate='chosen'
        run.candidates=[{'id':'chosen','assignments':[{'id':pid,'route_edge_ids':['door','hall']}]}]
        drill=db.get(DrillSession,demo['drill_id'])
        operations.append_event(db,drill,'indoor.door_changed','测试员','撤空后关门',{'door_id':'door','state':'closed'})
        db.commit()
        current={'simulation':{'residents':[{'id':pid,'status':'moving','node_id':'b'}],
            'spatial_network':{'edges':[{'id':'door','start_node_id':'a','end_node_id':'b'},
                                      {'id':'hall','start_node_id':'b','end_node_id':'c'}]}}}
        assert not relevant_changes(db,run,run.observed_sequence,current)
        current['simulation']['residents'][0]['node_id']='a'
        assert relevant_changes(db,run,run.observed_sequence,current)[0][0]=='needs_review'
        current['simulation']['residents'][0].update(node_id='c',status='evacuated')
        assert not relevant_changes(db,run,run.observed_sequence,current)
