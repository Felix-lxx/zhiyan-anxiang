from types import SimpleNamespace

from sqlalchemy import select

from app.api.routes import operations
from app.api.routes.auth import get_current_identity
from app.main import app
from app.models.agent import AgentDecisionCheck, AgentRun
from app.models.knowledge import KnowledgeDocument, KnowledgeExperience
from app.services.agent_outcomes import settle_checks
from test_exercise_world import exercise


def observed_plan(exercise, *, settle=True, changed_engine=False):
    client,headers,_,root,_,_,_,tick,start=exercise
    data=start()
    ids=[p['id'] for p in data['simulation']['residents'] if not p['vulnerable']][:2]
    response=client.post(root+'/agent/runs',headers=headers,json={'request_id':'experience-source-001',
        'goal':'分流疏散居民，核对走廊与出口安排','resident_ids':ids,'priority_assist':False})
    assert response.status_code==201,response.text
    plan=response.json();candidate=next(c for c in plan['candidates'] if c['can_apply'])
    approved=client.post(root+'/agent/runs/'+plan['id']+'/actions',headers=headers,json={
        'action':'approve','revision':1,'candidate_id':candidate['id']})
    assert approved.status_code==200,approved.text
    if changed_engine:
        with operations.SessionLocal() as session:
            check=session.scalar(select(AgentDecisionCheck).where(AgentDecisionCheck.run_id==plan['id']))
            check.basis={**check.basis,'forecast_engine_revision':'old-engine-version'};session.commit()
    if settle:
        tick(candidate['forecast_at']+candidate['forecast_seconds'])
        with operations.SessionLocal() as session:
            settle_checks(session,session.get(AgentRun,plan['id']),operations)
    return plan


def publish(client,headers,document):
    path='/api/v1/knowledge/documents/'+document['id']+'/actions'
    body={'version_id':document['versions'][0]['id']}
    for action in ['review','publish']:
        response=client.post(path,headers=headers,json={**body,'action':action})
        assert response.status_code==200,response.text


def test_observation_becomes_audited_draft_then_retrievable_experience(exercise):
    client,headers,_,root,*_=exercise
    plan=observed_plan(exercise)
    response=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1})
    assert response.status_code==200,response.text
    result=response.json();document=result['document'];source=document['experience']
    assert result['created'] and document['category']=='experience'
    assert document['versions'][0]['status']=='draft'
    assert source['population']==2 and source['revision']==1 and len(source['basis_hash'])==64
    assert source['forecast_engine_revision']==source['observed_engine_revision']
    actual=client.get(root+'/replay?at_seconds='+str(source['observed_at']),headers=headers).json()
    ids=set(plan['scope']['resident_ids'])
    assert source['actual']['arrived']==sum(p['status']=='evacuated' for p in actual['simulation']['residents'] if p['id'] in ids)
    duplicate=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1}).json()
    assert not duplicate['created'] and duplicate['document']['id']==document['id']
    query={'query':document['title'],'community_id':document['community_id'],'scenario':document['scenario']}
    before=client.post('/api/v1/knowledge/search',headers=headers,json=query).json()
    assert not any(hit['document_id']==document['id'] for hit in before['hits'])
    publish(client,headers,document)
    after=client.post('/api/v1/knowledge/search',headers=headers,json=query).json()
    hit=next(hit for hit in after['hits'] if hit['document_id']==document['id'])
    assert hit['experience']['basis_hash']==source['basis_hash']
    assert hit['experience']['actual']==source['actual']
    with operations.SessionLocal() as session:
        assert len(list(session.scalars(select(KnowledgeExperience))))==1


def test_pending_and_different_engine_results_cannot_become_experience(exercise):
    client,headers,*_=exercise
    plan=observed_plan(exercise,settle=False)
    response=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1})
    assert response.status_code==409
    with operations.SessionLocal() as session:
        assert not list(session.scalars(select(KnowledgeExperience)))


def test_model_version_change_is_recorded_and_blocks_comparison(exercise):
    client,headers,*_=exercise
    plan=observed_plan(exercise,changed_engine=True)
    with operations.SessionLocal() as session:
        check=session.scalar(select(AgentDecisionCheck).where(AgentDecisionCheck.run_id==plan['id']))
        assert not check.result['comparable'] and check.result['delta'] is None
        assert '修订号不同' in check.result['notice']
    response=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1})
    assert response.status_code==409


def test_other_account_cannot_generate_or_read_experience(exercise):
    client,headers,*_=exercise
    plan=observed_plan(exercise)
    document=client.post('/api/v1/knowledge/experiences',headers=headers,json={'run_id':plan['id'],'revision':1}).json()['document']
    app.dependency_overrides[get_current_identity]=lambda:SimpleNamespace(username='different-owner')
    try:
        assert client.post('/api/v1/knowledge/experiences',json={'run_id':plan['id'],'revision':1}).status_code==404
        assert client.get('/api/v1/knowledge/documents/'+document['id']).status_code==404
    finally:
        app.dependency_overrides.pop(get_current_identity,None)
