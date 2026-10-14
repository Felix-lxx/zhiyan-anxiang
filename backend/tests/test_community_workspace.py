from types import SimpleNamespace
from sqlalchemy import select
from app.api.routes import operations
from app.api.routes.auth import get_current_identity
from app.models.domain import RoadEdge, RoadEdgeStatus


def login(client):
    token=client.post('/api/v1/auth/login',json={'username':'admin','password':'Zhiyan@2026'}).json()['access_token']
    return {'Authorization':'Bearer '+token}


def test_community_edit_persists_rejects_stale_and_whitespace(client):
    headers=login(client)
    assert client.post('/api/v1/communities',headers=headers,json={'name':'   '}).status_code==422
    original=client.post('/api/v1/communities',headers=headers,json={'name':'测试社区'}).json()
    url='/api/v1/communities/'+original['id']
    payload={'name':'  新的社区名称  ','address':'示例路 18 号','description':'两栋住宅','expected_updated_at':original['updated_at']}
    saved=client.patch(url,headers=headers,json=payload)
    assert saved.status_code==200, saved.text
    assert client.get(url,headers=headers).json()['name']=='新的社区名称'
    assert client.patch(url,headers=headers,json=payload).status_code==409
    assert client.get(url,headers=headers).json()['description']=='两栋住宅'


def test_readiness_reflects_empty_data_and_blocked_routes(client):
    headers=login(client)
    empty=client.post('/api/v1/communities',headers=headers,json={'name':'空白社区'}).json()
    result=client.get('/api/v1/communities/'+empty['id']+'/readiness',headers=headers).json()
    assert result['passed_count']==0
    demo=client.post('/api/v1/communities/demo-ready',headers=headers).json()
    url='/api/v1/communities/'+demo['community']['id']+'/readiness'
    result=client.get(url,headers=headers)
    assert result.status_code==200, result.text
    assert next(c for c in result.json()['checks'] if c['key']=='scene')['passed']
    with operations.SessionLocal() as session:
        for edge in session.scalars(select(RoadEdge)): edge.status=RoadEdgeStatus.BLOCKED
        session.commit()
    result=client.get(url,headers=headers).json()
    assert not next(c for c in result['checks'] if c['key']=='roads')['passed']


def test_workspace_endpoints_do_not_expose_other_owners(client):
    headers=login(client)
    record=client.post('/api/v1/communities',headers=headers,json={'name':'私有社区'}).json()
    client.app.dependency_overrides[get_current_identity]=lambda:SimpleNamespace(username='another-owner')
    url='/api/v1/communities/'+record['id']
    assert client.get(url+'/readiness',headers=headers).status_code==404
    assert client.patch(url,headers=headers,json={'name':'越权修改','expected_updated_at':record['updated_at']}).status_code==404
