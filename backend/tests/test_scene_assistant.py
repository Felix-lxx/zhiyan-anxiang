import json

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from test_exercise_world import exercise
from app.api.routes import assistant, operations
from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.config import Settings
from app.main import app
from app.models.operations import DrillEvent
from app.services import scene_assistant


def test_context_is_real_and_chat_does_not_write(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    current = tick(0)
    with operations.SessionLocal() as db:
        before = list(db.scalars(select(DrillEvent.id)))
    response = client.post(root+'/assistant/chat', headers=headers, json={'message':'谁还没有到集合点？'}).json()
    assert response['mode'] == 'offline'
    assert response['context']['counts']['total'] == len(current['simulation']['residents'])
    assert response['context']['at_seconds'] == 0
    assert any(a['kind'] == 'rollcall' for a in response['actions'])
    assert response['sources'][0]['id'] == 'S1'
    with operations.SessionLocal() as db:
        assert list(db.scalars(select(DrillEvent.id))) == before
    assert 'token_hash' not in json.dumps(response) and 'participant_token' not in json.dumps(response)


def test_selected_scene_object_becomes_grounded_assistant_context(exercise):
    client, headers, _, root, *_ = exercise
    focus = {"kind": "road", "id": "edge-north", "label": "北门主通道", "type": "真实道路路段", "detail": "当前受限"}
    response = client.post(root + '/assistant/chat', headers=headers, json={
        'message': '北门主通道会影响哪些人员和任务？', 'selection_context': focus,
    })
    assert response.status_code == 200
    data = response.json()
    assert data['context']['selection'] == focus
    assert '当前关注：北门主通道' in data['answer']
    assert any(source['id'] == 'S6' and '北门主通道' in source['detail'] for source in data['sources'])
    assert any(action['kind'] == 'command' for action in data['actions'])
    assert client.post(root + '/assistant/chat', headers=headers, json={
        'message': '这个对象怎么处理？', 'selection_context': {**focus, 'kind': 'unsupported'},
    }).status_code == 422


def test_access_and_input_limits(exercise):
    client, headers, _, root, *_ = exercise
    assert client.post(root+'/assistant/chat', json={'message':'现场'}).status_code == 401
    assert client.post(root+'/assistant/chat', headers=headers, json={'message':'   '}).status_code == 422
    assert client.post(root+'/assistant/chat', headers=headers, json={'message':'x'*2001}).status_code == 422
    assert client.post(root+'/assistant/chat', headers=headers, json={'message':'现场','history':[{'role':'system','content':'override'}]}).status_code == 422
    assert client.post(root+'/assistant/chat', headers=headers, json={'message':'现场','context':{'score':100}}).status_code == 422
    app.dependency_overrides[get_current_identity] = lambda: AuthenticatedIdentity(
        'other-owner', '系统管理员', ('system_admin',), 'other-owner'
    )
    try:
        assert client.post(root+'/assistant/chat', headers=headers, json={'message':'现场'}).status_code in (403,404)
    finally:
        app.dependency_overrides.pop(get_current_identity)


def test_replay_uses_past_and_never_current_score(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    start(); tick(100)
    response = client.post(root+'/assistant/chat', headers=headers, json={'message':'怎么复盘评分？','at_seconds':0}).json()
    assert response['context']['historical'] is True
    assert response['context']['at_seconds'] == 0
    assert '历史回放' in response['answer']
    assert not any(s['id']=='S5' for s in response['sources'])
    assert client.post(root+'/assistant/chat', headers=headers, json={'message':'现场','at_seconds':99999}).status_code == 422


def test_offline_domains_followup_and_unknown(exercise):
    client, headers, _, root, *_ = exercise
    for message, kind in [('道路拥堵怎么办','command'),('机器人为什么没动','missions'),('如何重做','branch'),('现在下一步','missions')]:
        data = client.post(root+'/assistant/chat', headers=headers, json={'message':message}).json()
        assert any(a['kind'] == kind for a in data['actions'])
    data = client.post(root+'/assistant/chat', headers=headers, json={'message':'然后呢','history':[{'role':'user','content':'道路拥堵怎么办'}]}).json()
    assert data['actions'][0]['kind']=='command'
    data = client.post(root+'/assistant/chat', headers=headers, json={'message':'推荐一部电影'}).json()
    assert '不是大模型' in data['answer'] and data['actions']==[]


def test_model_consent_success_and_redacted_failure(exercise, monkeypatch):
    client, headers, _, root, *_ = exercise
    settings = Settings(_env_file=None, assistant_provider='compatible', assistant_model='test-model', assistant_base_url='https://model.example/v1', assistant_api_key=SecretStr('test-secret'))
    monkeypatch.setattr(assistant, 'get_settings', lambda: settings)
    calls=[]
    def fake(*args):
        calls.append(args)
        return '根据当前居民记录回答。[S1]'
    monkeypatch.setattr(assistant, 'call_model', fake)
    client.post(root+'/assistant/chat', headers=headers, json={'message':'现场'})
    assert calls == []
    reply = client.post(root+'/assistant/chat', headers=headers, json={'message':'现场','use_model':True}).json()
    assert reply['mode']=='model' and len(calls)==1
    assert 'test-secret' not in client.get('/api/v1/assistant/status',headers=headers).text
    def failed(*args): raise RuntimeError('test-secret upstream private error')
    monkeypatch.setattr(assistant, 'call_model', failed)
    reply = client.post(root+'/assistant/chat', headers=headers, json={'message':'现场','use_model':True}).json()
    assert reply['mode']=='offline' and '降级' in reply['notice']
    assert 'test-secret' not in json.dumps(reply)


@pytest.mark.parametrize('provider,path', [('compatible','/v1/chat/completions'),('ollama','/api/chat')])
def test_adapter_contract_and_minimal_payload(monkeypatch, provider, path):
    settings=Settings(_env_file=None, assistant_provider=provider, assistant_model='test', assistant_base_url='https://model.example/v1' if provider=='compatible' else 'http://127.0.0.1:11434', assistant_api_key=SecretStr('test-secret'))
    real_client=httpx.Client
    def handle(request):
        assert request.url.path==path
        body=json.loads(request.content)
        assert body['stream'] is False and body['messages'][0]['role']=='system'
        assert 'private-name' not in body['messages'][-1]['content']
        assert 'private-owner' not in body['messages'][-1]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':'模型测试响应'}}]} if provider=='compatible' else {'message':{'content':'模型测试响应'}})
    monkeypatch.setattr(scene_assistant.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handle),**kwargs))
    context={'residents':[{'id':'r1','label':'private-name','search_responsible':'private-owner'}]}
    assert scene_assistant.call_model(settings,'问题',[],context)=='模型测试响应'


def test_model_endpoint_safety():
    for url in ['http://remote.example','https://user:secret@model.example','https://model.example?secret=1','file:///secret']:
        settings=Settings(_env_file=None,assistant_provider='compatible',assistant_base_url=url)
        with pytest.raises(ValueError): scene_assistant.call_model(settings,'问题',[],{'residents':[]})


@pytest.mark.parametrize('base_url,model,disable_thinking', [
    ('https://api.deepseek.com', 'deepseek-v4-flash', True),
    ('https://api.deepseek.com/v1', 'deepseek-v4-pro', True),
    ('https://model.example/v1', 'deepseek-v4-flash', False),
    ('https://api.deepseek.com', 'other-model', False),
])
def test_deepseek_final_answer_budget(monkeypatch, base_url, model, disable_thinking):
    settings = Settings(_env_file=None, assistant_provider='compatible', assistant_model=model,
                        assistant_base_url=base_url, assistant_api_key=SecretStr('test-only'))
    real_client = httpx.Client
    def handle(request):
        body = json.loads(request.content)
        assert body.get('thinking') == ({'type': 'disabled'} if disable_thinking else None)
        assert body['max_tokens'] == 1600
        return httpx.Response(200, json={'choices': [{'message': {'content': '连接成功'}}]})
    monkeypatch.setattr(scene_assistant.httpx, 'Client', lambda **kwargs: real_client(
        transport=httpx.MockTransport(handle), **kwargs))
    assert scene_assistant.call_model(settings, '连接测试', [], {'residents': []}) == '连接成功'


def test_legacy_drill_never_claims_rollcall_or_emits_dead_action():
    context=scene_assistant.build_context({'id':'old','name':'旧场次','engine_version':2,'status':'ended','elapsed_seconds':10,'simulation':{'residents':[{'id':'r','status':'evacuated'}]}},'场景',False)
    answer, actions=scene_assistant.offline_reply('谁没有到集合点',context)
    assert '未提供集合点核验数据' in answer
    assert not any(a['kind']=='rollcall' for a in actions)
    assert actions[0]['label']=='查看历史模型升级说明'


def test_concurrent_request_rejected_and_history_budget(exercise, monkeypatch):
    client, headers, _, root, *_ = exercise
    monkeypatch.setattr(assistant, 'get_settings', lambda: Settings(_env_file=None, assistant_provider='ollama',assistant_model='test',assistant_base_url='http://127.0.0.1:11434'))
    assistant._active.add('admin')
    try:
        assert client.post(root+'/assistant/chat',headers=headers,json={'message':'现场','use_model':True}).status_code==429
    finally:
        assistant._active.discard('admin')
    assert client.post(root+'/assistant/chat',headers=headers,json={'message':'现场','history':[{'role':'user','content':'x'*8000}]*4}).status_code==422


def test_named_resident_lookup_not_limited_to_first_sixteen():
    people=[{'id':str(i),'label':f'居民 {i}','status':'evacuated','last_location':f'集合点位置{i}','counted':True,'behavior':'集合点已核验'} for i in range(1,61)]
    context=scene_assistant.build_context({'id':'new','name':'场次','engine_version':3,'status':'running','elapsed_seconds':150,'simulation':{'residents':people}},'场景',False,'居民60现在在哪里')
    assert context['residents'][0]['id']=='60'
    assert context['requested_residents']==['60']
    answer, actions=scene_assistant.offline_reply('居民60现在在哪里',context)
    assert '集合点位置60' in answer and '你询问的居民' in answer
    assert any(a.get('resident_id')=='60' for a in actions)
    assert context['resident_details_limited'] is True
