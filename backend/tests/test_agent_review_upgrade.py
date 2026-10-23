from app.api.routes import operations
from app.models.agent import AgentRun
from app.services.agent_workflow import advance_run
from app.services.agent_containment import occupied, source_door
from types import SimpleNamespace
from test_kitchen_fire import kitchen


def test_review_pause_approval_and_containment_are_real_commands(kitchen):
    client, headers, _, _, drill, base, tick = kitchen
    assert client.patch(base+'/state', headers=headers, json={'action':'start'}).status_code == 200
    data = tick(44)
    model=data['simulation']['world']['indoor_environment']
    door=next(d for d in model['doors'] if d['room_id']==model['source_zone_id'])
    assert client.post(base+'/commands', headers=headers, json={'command_id':'open-review-door-001',
        'kind':'indoor.door.set','arguments':{'door_id':door['id'],'state':'open'}}).status_code == 200
    response=client.post(base+'/agent/runs', headers=headers, json={'request_id':'review-upgrade-001',
        'goal':'疏散居民并护送重点人员','pause_for_review':True,'include_case_tasks':True})
    assert response.status_code == 201, response.text
    run=response.json()
    assert client.get(base,headers=headers).json()['status']=='paused'
    assert run['approval_guard']['can_approve']
    assert len(run['task_graph']['case_tasks'])==4
    candidate=next(c for c in run['candidates'] if c['allocation']['rule']=='containment')
    assert any(s.get('kind')=='indoor.door.set' for s in candidate['groups'])
    approved=client.post(base+'/agent/runs/'+run['id']+'/actions', headers=headers,
        json={'action':'approve','revision':1,'candidate_id':candidate['id']})
    assert approved.status_code==200,approved.text
    assert client.get(base,headers=headers).json()['status']=='running'
    step=next(s for s in approved.json()['steps'] if s['kind']=='indoor.door.set')
    assert step['status']=='waiting'  # occupied source room must remain passable
    for t in (74,104,144,204,284):
        tick(t)
        with operations.SessionLocal() as db:
            advance_run(db,db.get(AgentRun,run['id']),SimpleNamespace(username='admin'))
    final=client.get(base,headers=headers).json()
    closed=next(d for d in final['simulation']['environment']['indoor']['doors'] if d['id']==door['id'])
    assert closed['state']=='closed'
    receipts=[c for c in final['commands'] if c['kind']=='indoor.door.set' and c.get('origin',{}).get('kind')=='agent']
    assert len(receipts)==1 and receipts[0]['status']=='completed'
    # Evacuation alone cannot complete the case responsibilities.
    result=client.get(base+'/agent/runs',headers=headers).json()['runs'][0]
    assert result['status']!='completed'


def test_teaching_deadlines_are_frozen_only_for_new_run(kitchen):
    client,headers,root,_,old,base,_=kitchen
    created=client.post(root+'/drills',headers=headers,json={'name':'教学训练','training_mode':'teaching'})
    assert created.status_code==201,created.text
    world=created.json()['simulation']['world']
    assert world['parameters']['training_mode']=='teaching'
    tasks={t['kind']:t for t in world['tasks']}
    assert tasks['escort']['deadline_seconds']>=600
    assert tasks['gas_off']['deadline_seconds']>=300
    assert all(t['deadline_seconds']==180 for t in client.get(base,headers=headers).json()['simulation']['world']['tasks'])


def test_containment_occupancy_handles_room_and_door():
    room={'id':'room','height':0,'x':10,'y':10,'width':4,'depth':4}
    data={'simulation':{'world':{'indoor_environment':{'node_zones':{'node':'room'},'zones':[room]}},
        'residents':[{'node_id':'node','status':'waiting'}], 'helpers':[],
        'environment':{'indoor':{'source_zone_id':'room','doors':[{'id':'door','room_id':'room'}]}}}}
    door=source_door(data)
    assert occupied(data,door)
    data['simulation']['residents'][0]={'status':'moving','current_edge_id':'door'}
    assert occupied(data,door)
    data['simulation']['residents'][0]={'status':'evacuated'}
    assert not occupied(data,door)
