import base64
import json
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from types import SimpleNamespace

from pypdf import PdfWriter
from app.api.routes.auth import get_current_identity
from app.api.routes import operations
from app.core.config import get_settings, Settings
from app.main import app
from app.services.knowledge_ingestion import extract
from test_exercise_world import exercise


def login(client):
    response = client.post('/api/v1/auth/login', json={'username':'admin','password':get_settings().bootstrap_admin_password})
    return {'Authorization':'Bearer '+response.json()['access_token']}


def publish(client, headers, doc):
    root = '/api/v1/knowledge/documents/' + doc['id']
    version = doc['versions'][0]['id']
    review = client.post(root+'/actions', headers=headers, json={'action':'review','version_id':version})
    assert review.status_code == 200, review.text
    result = client.post(root+'/actions', headers=headers, json={'action':'publish','version_id':version})
    assert result.status_code == 200, result.text
    return result.json()


def test_seed_sources_are_readonly_and_repeatable(client):
    headers = login(client)
    for _ in range(2):
        response = client.get('/api/v1/knowledge/documents', headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()
        catalog=Path(__file__).parents[1]/'app'/'data'/'fire_knowledge.json'
        assert data['total'] == len(json.loads(catalog.read_text(encoding='utf-8')))
    official = [d for d in data['items'] if d['category']=='official_summary']
    assert len(official)==6 and all(d['source_url'].startswith('https://') for d in official)
    result = client.post('/api/v1/knowledge/documents/'+official[0]['id']+'/actions', headers=headers,
                         json={'action':'withdraw','version_id':official[0]['versions'][0]['id']})
    assert result.status_code == 403
    assert client.get('/api/v1/knowledge/documents').status_code == 401


def test_published_retrieval_revision_withdrawal_and_pinned_evidence(client):
    headers = login(client)
    payload = {'title':'青槐社区护送预案','content':'青槐社区采用重点居民护送登记制度。独居老人由已登记值守员负责会合，再沿核验路线到集合点。','scenario':'kitchen_fire'}
    response = client.post('/api/v1/knowledge/documents', headers=headers, json=payload)
    assert response.status_code == 201, response.text
    doc = response.json()
    search = {'query':'青槐社区护送登记','scenario':'kitchen_fire'}
    assert not client.post('/api/v1/knowledge/search', headers=headers, json=search).json()['hits']
    publish(client, headers, doc)
    first = client.post('/api/v1/knowledge/search', headers=headers, json=search).json()
    assert first['hits'][0]['document_id'] == doc['id'] and first['hits'][0]['version']==1
    assert first['hits'][0]['content_hash'] == doc['versions'][0]['chunks'][0]['content_hash']
    payload['content'] = '青槐社区护送登记已修订：新增两名值守员。所有到达居民还需逐人提交集合清点记录。'
    revised = client.post('/api/v1/knowledge/documents/'+doc['id']+'/versions', headers=headers, json=payload).json()
    updated = publish(client, headers, revised)
    second = client.post('/api/v1/knowledge/search', headers=headers, json=search).json()
    assert second['hits'][0]['version']==2 and '新增两名' in second['hits'][0]['content']
    old = client.get('/api/v1/knowledge/retrievals/'+first['retrieval_id'], headers=headers).json()
    assert old['hits'][0]['content']==first['hits'][0]['content'] and old['hits'][0]['version']==1
    withdrawn = client.post('/api/v1/knowledge/documents/'+doc['id']+'/actions', headers=headers,
        json={'action':'withdraw','version_id':updated['versions'][0]['id']})
    assert withdrawn.status_code == 200
    assert not client.post('/api/v1/knowledge/search', headers=headers, json=search).json()['hits']


def test_cross_account_cannot_read_private_docs_or_retrievals(client):
    headers = login(client)
    doc = client.post('/api/v1/knowledge/documents', headers=headers, json={
        'title':'私有青槐安排','content':'私有青槐居民联系方式与值守人员安排，仅供该账号维护，请勿公开。'}).json()
    publish(client, headers, doc)
    evidence = client.post('/api/v1/knowledge/search', headers=headers, json={'query':'私有青槐'}).json()
    app.dependency_overrides[get_current_identity] = lambda: SimpleNamespace(username='outsider',role_codes=(),role='test',user_id='outsider')
    try:
        assert client.get('/api/v1/knowledge/documents/'+doc['id']).status_code==404
        assert client.get('/api/v1/knowledge/retrievals/'+evidence['retrieval_id']).status_code==404
        assert not client.post('/api/v1/knowledge/search', json={'query':'私有青槐'}).json()['hits']
    finally:
        app.dependency_overrides.pop(get_current_identity)


def test_file_extraction_and_failure_are_real_states(client):
    headers = login(client)
    encoded = base64.b64encode('社区厨房预案：居民护送与清点需要核对每名人员的实际到场状态。'.encode()).decode()
    response = client.post('/api/v1/knowledge/documents', headers=headers, json={
        'title':'上传预案','filename':'plan.txt','file_base64':encoded})
    assert response.status_code==201, response.text
    assert response.json()['versions'][0]['chunks'][0]['content'].startswith('社区厨房')
    writer = PdfWriter(); writer.add_blank_page(width=200,height=200); buffer = BytesIO(); writer.write(buffer)
    failure = client.post('/api/v1/knowledge/documents', headers=headers, json={
        'title':'无文字扫描件','filename':'empty.pdf','file_base64':base64.b64encode(buffer.getvalue()).decode()}).json()
    assert failure['versions'][0]['status']=='failed' and not failure['versions'][0]['chunks']
    denied = client.post('/api/v1/knowledge/documents/'+failure['id']+'/actions',headers=headers,
        json={'action':'review','version_id':failure['versions'][0]['id']})
    assert denied.status_code==409
    assert client.delete('/api/v1/knowledge/documents/'+failure['id'],headers=headers).status_code==200


def test_docx_does_not_execute_fields_and_returns_paragraphs():
    buffer = BytesIO()
    with ZipFile(buffer,'w') as archive:
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>厨房预案包含烟气检查、居民护送以及集合清点的实际操作步骤。</w:t></w:r></w:p></w:body></w:document>')
    pages, kind = extract('plan.docx',base64.b64encode(buffer.getvalue()).decode())
    assert kind=='docx' and '集合清点' in pages[0][1]


def test_optional_semantic_index_and_explicit_fallback(client, monkeypatch):
    from app.services import knowledge_vectors
    settings = Settings(_env_file=None,knowledge_embedding_url='https://embedding.example/v1/embeddings',knowledge_embedding_model='test-vector')
    monkeypatch.setattr(knowledge_vectors,'get_settings',lambda:settings)
    monkeypatch.setattr(knowledge_vectors,'embed',lambda texts:[[1.,0.,0.,0.,0.,0.,0.,0.] for _ in texts])
    headers=login(client)
    doc=client.post('/api/v1/knowledge/documents',headers=headers,json={
        'title':'专属协作约定','content':'社区使用红色标记记录需要护送的居民，并在集合点由指定人员逐一清点。'}).json()
    publish(client,headers,doc)
    assert client.post('/api/v1/knowledge/documents/'+doc['id']+'/index',headers=headers).status_code==200
    result=client.post('/api/v1/knowledge/search',headers=headers,json={'query':'特别关照的住户','semantic':True}).json()
    assert result['method']=='hybrid' and result['hits'][0]['document_id']==doc['id']
    def failed(_): raise RuntimeError('upstream credentials must not leak')
    monkeypatch.setattr(knowledge_vectors,'embed',failed)
    fallback=client.post('/api/v1/knowledge/search',headers=headers,json={'query':'集合点清点','semantic':True}).json()
    assert fallback['method']=='keyword' and '回退' in fallback['notice'] and 'credentials' not in str(fallback)


def test_assistant_uses_scenario_knowledge_and_keeps_drill_state(exercise):
    client,headers,_,root,*_=exercise
    client.get('/api/v1/knowledge/documents',headers=headers)
    response=client.post(root+'/assistant/chat',headers=headers,json={'message':'充电棚道路堵了怎么办？'})
    assert response.status_code==200,response.text
    data=response.json()
    assert data['knowledge']['method']=='keyword' and data['knowledge']['hits']
    assert '[K' in data['answer'] and any(s['id'].startswith('K') for s in data['sources'])
    assert all(h['scenario'] in {'all','charging_shed'} for h in data['knowledge']['hits'])


def test_oversize_json_is_rejected_before_model_validation(client):
    response=client.post('/api/v1/knowledge/documents',content=b'x'*4_300_001,
                         headers={'Content-Type':'application/json'})
    assert response.status_code==413


def test_model_cannot_invent_knowledge_citations(exercise, monkeypatch):
    from app.api.routes import assistant
    client,headers,_,root,*_=exercise
    client.get('/api/v1/knowledge/documents',headers=headers)
    settings=Settings(_env_file=None,assistant_provider='compatible',assistant_model='test',
                      assistant_base_url='https://model.example/v1',assistant_api_key='test')
    monkeypatch.setattr(assistant,'get_settings',lambda:settings)
    monkeypatch.setattr(assistant,'call_model',lambda *args:'依据不存在的资料可直接完成任务。[K999]')
    response=client.post(root+'/assistant/chat',headers=headers,json={'message':'充电棚道路堵了怎么办','use_model':True})
    assert response.status_code==200,response.text
    result=response.json()
    assert result['mode']=='offline' and '[K999]' not in result['answer']
    assert result['knowledge']['hits']


def test_goal_proposal_freezes_knowledge_version(exercise):
    client,headers,_,root,*_=exercise
    client.get('/api/v1/knowledge/documents',headers=headers)
    response=client.post(root+'/agent/runs',headers=headers,json={'request_id':'knowledge-plan-freeze',
        'goal':'将居民分流疏散并优先护送独居老人','priority_assist':True})
    assert response.status_code==201,response.text
    plan=response.json()
    assert plan['knowledge']['hits'] and plan['knowledge']['retrieval_id']
    with operations.SessionLocal() as db:
        from app.models.agent import AgentRun
        stored=db.get(AgentRun,plan['id'])
        assert stored.scope['knowledge']==plan['knowledge']


def test_database_rejects_two_published_versions(client):
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from app.models.knowledge import KnowledgeVersion
    import pytest
    headers=login(client)
    payload={'title':'版本唯一性资料','content':'社区资料经过审核发布后，同一份资料只能保留一个当前发布版本供检索使用。'}
    doc=client.post('/api/v1/knowledge/documents',headers=headers,json=payload).json()
    client.post('/api/v1/knowledge/documents/'+doc['id']+'/versions',headers=headers,json=payload)
    with operations.SessionLocal() as db:
        versions=list(db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id==doc['id'])))
        for version in versions:version.status='published'
        with pytest.raises(IntegrityError):db.commit()
        db.rollback()


def test_expired_published_content_is_not_retrieved(client):
    from datetime import UTC, datetime, timedelta
    from app.models.knowledge import KnowledgeVersion
    headers=login(client)
    doc=client.post('/api/v1/knowledge/documents',headers=headers,json={
        'title':'槐荫有效期预案','content':'槐荫有效期预案用于检验到期资料不再进入当前发布知识检索，历史证据不变。',
        'valid_until':(datetime.now(UTC)+timedelta(days=1)).isoformat()}).json()
    publish(client,headers,doc)
    with operations.SessionLocal() as db:
        db.get(KnowledgeVersion,doc['versions'][0]['id']).valid_until=datetime.now(UTC)-timedelta(days=1)
        db.commit()
    response=client.post('/api/v1/knowledge/search',headers=headers,json={'query':'槐荫有效期预案'}).json()
    assert not response['hits']
    detail=client.get('/api/v1/knowledge/documents/'+doc['id'],headers=headers).json()
    assert detail['versions'][0]['effective_status']=='expired'
