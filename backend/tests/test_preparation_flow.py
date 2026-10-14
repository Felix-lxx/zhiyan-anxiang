from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from sqlalchemy import select
from app.api.routes import operations
from app.api.routes.auth import get_current_identity
from app.models.domain import Scene, SceneVersion
from app.models.operations import DrillSession, DrillEvent, DrillScore
from app.models.tasks import DecisionTask
from app.services.scenes import update_charging_shed_parameters
from test_community_workspace import login


def test_history_paginates_across_scenes_and_keeps_frozen_population(client):
    headers=login(client)
    demo=client.post('/api/v1/communities/demo-ready',headers=headers).json()
    community_id=demo['community']['id']
    with operations.SessionLocal() as session:
        first=session.scalar(select(Scene).where(Scene.community_id==community_id))
        second=Scene(community_id=community_id,template_id=first.template_id,name='南楼演练')
        session.add(second);session.flush()
        version=SceneVersion(scene_id=second.id,community_version_id=first.versions[-1].community_version_id,
                             version_number=1,parameters=first.versions[-1].parameters)
        session.add(version);session.flush()
        for i in range(25):
            drill=DrillSession(scene_id=first.id if i%2==0 else second.id,
                scene_version_id=first.versions[-1].id if i%2==0 else version.id,
                name='100%练习' if i==0 else f'练习 {i}',status='paused' if i==0 else 'ended',
                created_at=datetime(2026,10,14,tzinfo=UTC)+timedelta(seconds=i))
            session.add(drill);session.flush()
            session.add(DrillEvent(drill_session_id=drill.id,sequence=1,event_type='drill.created',actor='系统',message='测试',
                payload={'world':{'parameters':{'resident_count':37}}}))
            if i==24: session.add(DrillScore(drill_session_id=drill.id,total_score=95,details=[],recommendations=['护送及时']))
        session.commit()
    url=f'/api/v1/communities/{community_id}/drill-history'
    response=client.get(url,headers=headers,params={'search':'练习'});assert response.status_code==200,response.text
    page=response.json();assert page['matched']==25 and len(page['items'])==20
    assert len({row['sceneId'] for row in page['items']})==2
    assert page['items'][0]['resident_count']==37
    assert page['latest_unfinished']['name']=='100%练习'
    tail=client.get(url,headers=headers,params={'search':'练习','page':2}).json()
    assert len(tail['items'])==5 and not {row['id'] for row in page['items']} & {row['id'] for row in tail['items']}
    assert client.get(url+'?search=%25',headers=headers).json()['matched']==1
    assert client.get(url+'?sort=score',headers=headers).json()['items'][0]['score']['total_score']==95
    assert client.get(url+'?start=2026-10-15T00:00:00Z&end=2026-10-14T00:00:00Z',headers=headers).status_code==422
    assert client.get(url+'?page_size=1000',headers=headers).status_code==422
    client.app.dependency_overrides[get_current_identity]=lambda:SimpleNamespace(username='other-owner')
    assert client.get(url,headers=headers).status_code==404


def test_invalid_fire_source_is_consistent_in_check_publish_and_new_drill(client):
    headers=login(client)
    demo=client.post('/api/v1/communities/demo-ready',headers=headers).json()
    community_id=demo['community']['id']
    with operations.SessionLocal() as session:
        scene=session.scalar(select(Scene).where(Scene.community_id==community_id))
        scene_id=scene.id
        scene.versions[-1].parameters={**scene.versions[-1].parameters,'fire_source_object_id':'deleted-source'}
        session.commit()
    base=f'/api/v1/scenes/{scene_id}'
    result=client.post(base+'/validate',headers=headers).json()
    assert not result['passed']
    assert result['issue_details'][0]['query']['field']=='fire-source'
    assert client.post(base+'/publish',headers=headers).status_code==422
    assert client.post(base+'/drills',headers=headers,json={'name':'不应创建','time_scale':1}).status_code==422
    readiness=client.get(f'/api/v1/communities/{community_id}/readiness',headers=headers).json()
    issue=next(check for check in readiness['checks'] if check['key']=='scene')
    assert not issue['passed'] and issue['query']['scene']==scene_id


def test_editing_published_scene_preserves_tasks_in_new_draft(client):
    headers=login(client)
    demo=client.post('/api/v1/communities/demo-ready',headers=headers).json()
    with operations.SessionLocal() as session:
        scene=session.scalar(select(Scene).where(Scene.community_id==demo['community']['id']))
        old=scene.versions[-1]
        before=list(session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id==old.id)))
        assert before
        update_charging_shed_parameters(session,scene=scene,parameters={**old.parameters,'resident_count':93})
        session.expire_all()
        scene=session.get(Scene,scene.id)
        draft=scene.versions[-1]
        tasks=list(session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id==draft.id)))
        assert draft.id!=old.id and len(tasks)==len(before)
        assert {task.title for task in tasks}=={task.title for task in before}
        assert all(task.decision_point_id in {point.id for point in draft.decision_points} for task in tasks)
        assert len(list(session.scalars(select(DecisionTask).where(DecisionTask.scene_version_id==old.id))))==len(before)
