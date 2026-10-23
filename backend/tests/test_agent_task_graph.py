from copy import deepcopy
from types import SimpleNamespace
import pytest
from sqlalchemy import select, delete
from app.api.routes import operations
from app.models.agent import AgentRun, AgentResourceClaim
from app.models.operations import DrillCommand, DrillEvent
from app.models.tasks import DecisionTask
from app.services.agent_workflow import advance_run
from app.services.agent_task_graph import compile_graph, validate_graph
from test_exercise_world import exercise
from test_agent_workflow import proposal


def test_dependency_validation_and_escort_waves():
    graph=compile_graph([{'id':'first','label':'第一批','resident_ids':['a'],'action':'priority_assist'},
                         {'id':'parallel','label':'分流','resident_ids':['b'],'action':'evacuate'},
                         {'id':'second','label':'第二批','resident_ids':['c'],'action':'priority_assist'}],0)
    assert graph[1]['depends_on']==[] and graph[2]['depends_on']==['first']
    graph[0]['depends_on']=['second']
    with pytest.raises(ValueError,match='循环'): validate_graph(graph)


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
        result=client.post(root+'/agent/runs/'+run['id']+'/actions',headers=headers,json={'action':'approve','revision':1,'candidate_id':next(c['id'] for c in run['candidates'] if c['can_apply'])})
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
        assert db.get(AgentRun,second['id']).status=='waiting'  # physical helper has not finished


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
