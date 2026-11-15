from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillSession
from app.schemas.scene import ChargingShedParametersUpdate
from app.services.agent_workflow import advance_run
from app.services.population_profiles import assign_profiles
from test_community_training import community_run  # noqa: F401
from test_exercise_world import exercise  # noqa: F401


def profile(**overrides):
    return {'mobility_count':3,'direct_contact_count':8,'sleeping_count':8,**overrides}


def test_independent_traits_allow_overlap_without_slowing_direct_contact_members():
    parameters={'simulation_seed':37,'population_profile':profile()}
    people=[{'id':f'p{i}'} for i in range(8)]
    frozen=assign_profiles(people,parameters)
    assert sum(p['vulnerable'] for p in people)==3
    assert all(p['notification_need']=='direct_contact' and p['preparation_seconds']==25 for p in people)
    assert all(p['walking_speed']==1.25 for p in people if not p['vulnerable'])
    assert all(p['walking_speed']==.65 for p in people if p['vulnerable'])
    assert frozen['overlap_count']==8
    repeated=[{'id':f'p{i}'} for i in range(8)]
    assign_profiles(repeated,parameters)
    assert repeated==people
    parameters['population_profile']['direct_contact_count']=2
    changed=[{'id':f'p{i}'} for i in range(8)]
    assign_profiles(changed,parameters)
    for trait in ('mobility','sleeping'):
        assert {p['id'] for p in changed if trait in p['traits']}=={p['id'] for p in people if trait in p['traits']}


def test_profile_validation_and_patch_serialization_keep_response_defaults():
    base={'fire_source_object_id':'source','start_time':'20:15','wind_direction':'微风',
          'resident_count':8,'hydrant_status':'available','south_lane_status':'open','community_profile':'night_shift'}
    model=ChargingShedParametersUpdate(**base,population_profile=profile())
    saved=model.model_dump(exclude_unset=True)['population_profile']
    assert saved['walking_speed']==1.25 and saved['awake_preparation_seconds']==8
    for invalid in [profile(mobility_count=9),profile(mobility_count=True),
                    profile(mobility_walking_speed=1.2,walking_speed=1),
                    profile(awake_preparation_seconds=30,sleeping_preparation_seconds=10),
                    profile(unrecognized=True)]:
        with pytest.raises(ValidationError):
            ChargingShedParametersUpdate(**base,population_profile=invalid)
    with pytest.raises(ValidationError):
        ChargingShedParametersUpdate(**{**base,'community_profile':'legacy'},population_profile=profile())


def test_configured_profile_persists_freezes_and_respects_shared_staff(community_run):
    client,headers,old_root,data,_,clock,_=community_run
    with operations.SessionLocal() as db:
        scene='/api/v1/scenes/'+db.get(DrillSession,old_root.rsplit('/',1)[-1]).scene_id
    old_world=deepcopy(data['simulation']['world'])
    parameters={**old_world['parameters'],'population_profile':profile()}
    saved=client.patch(scene+'/parameters',headers=headers,json=parameters)
    assert saved.status_code==200,saved.text
    assert saved.json()['versions'][-1]['parameters']['population_profile']['walking_speed']==1.25
    reduced={**parameters,'resident_count':2}
    reduced.pop('population_profile')
    denied=client.patch(scene+'/parameters',headers=headers,json=reduced)
    assert denied.status_code==422 and '成员需求' in denied.text
    from app.models.domain import Scene
    from app.services.scene_validation import validate_configuration
    with operations.SessionLocal() as db:
        result=validate_configuration(db,db.get(Scene,scene.rsplit('/',1)[-1]),
                                      {'population_profile':profile(mobility_count=9)})
    assert not result['passed']
    assert any(issue['query']['field']=='population-profile' for issue in result['issue_details'])
    assert client.post(scene+'/publish',headers=headers).status_code==200
    response=client.post(scene+'/drills',headers=headers,json={'name':'复合需求与有限接应','training_mode':'teaching'})
    assert response.status_code==201,response.text
    root='/api/v1/drills/'+response.json()['id']
    clock['t']=0
    assert client.patch(root+'/state',headers=headers,json={'action':'start'}).status_code==200
    def tick(at):
        clock['t']=at
        with operations.SessionLocal() as db:
            operations.advance_engine(db,db.get(DrillSession,response.json()['id']))
        return client.get(root,headers=headers).json()
    initial=tick(0);arrival=initial['robot']['task_queue'][0]['ends_at_seconds']
    for at in (arrival,arrival+2,arrival+4):current=tick(at)
    people=current['simulation']['residents']
    assert sum(p['vulnerable'] for p in people)==3
    assert current['simulation']['community']['summary']['assistance_pending']==3
    assert current['simulation']['community']['population']['overlap_count']==8
    assert client.get(old_root,headers=headers).json()['simulation']['world']==old_world
    assert client.get(root+'/replay?at_seconds=0',headers=headers).json()['simulation']['world']==current['simulation']['world']
    for house in current['simulation']['community']['households']:
        for action in ('household_notified','household_confirmed'):
            result=client.post(root+'/participant-actions',headers=headers,json={
                'role':'物业/网格员','household_id':house['id'],'channel':'phone','action':action,
                'message':'电话核对本户居民已收到演练通知'})
            assert result.status_code==200,result.text
    proposed=client.post(root+'/agent/runs',headers=headers,json={
        'request_id':'composite-needs-plan-001','goal':'分流全部居民并依次护送重点人员',
        'priority_assist':True,'robot_broadcast':False,'pause_for_review':False})
    assert proposed.status_code==201,proposed.text
    plan=proposed.json();candidate=next(c for c in plan['candidates'] if c['can_apply'] and not c.get('vehicle_support'))
    approved=client.post(root+'/agent/runs/'+plan['id']+'/actions',headers=headers,json={
        'action':'approve','revision':plan['revision'],'candidate_id':candidate['id']})
    assert approved.status_code==200,approved.text
    with operations.SessionLocal() as db:
        advance_run(db,db.get(AgentRun,plan['id']),SimpleNamespace(username='admin'))
    live=client.get(root,headers=headers).json()
    active=[h for h in live['simulation']['helpers'] if h['state']!='completed']
    assert 0<len(active)<=2
    assert len({h['staff_id'] for h in active})==len(active)
    run=next(p for p in client.get(root+'/agent/runs',headers=headers).json()['runs'] if p['id']==plan['id'])
    assert any(s['action']=='priority_assist' and not s['execution']['command_recorded'] for s in run['steps'] if s.get('action'))
    ended=client.patch(root+'/state',headers=headers,json={'action':'end'})
    assert ended.status_code==200,ended.text
    archive=client.get(root+'/archive',headers=headers).json()['archive']['data']
    recorded={p['id']:p for p in archive['final_state']['residents']}
    for person in ended.json()['simulation']['residents']:
        assert recorded[person['id']]['traits']==person['traits']
        assert recorded[person['id']]['preparation_seconds']==person['preparation_seconds']
        assert recorded[person['id']]['household_id']==person['household_id']
