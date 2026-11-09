"""Behavioral regression for durable archives, reviewed reuse and private chat."""
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.routes import operations
from app.api.routes.assistant import ChatRequest
from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.main import app
from app.models.operations import DrillSession
from app.models.training import AssistantExchange, DrillArchive
from app.services.assistant_conversations import prepare_request, save_exchange
from app.services.knowledge_ingestion import digest
from test_exercise_world import exercise
from test_knowledge_experience import publish


def end_training(exercise):
    client, headers, _, root, *_ = exercise
    assert client.patch(root+'/state', headers=headers, json={'action':'start'}).status_code == 200
    response = client.patch(root+'/state', headers=headers, json={'action':'end'})
    assert response.status_code == 200, response.text
    return response.json()


def test_unsuccessful_manual_run_archived_once_and_only_reviewed_experience_is_retrievable(exercise):
    client, headers, _, root, *_ = exercise
    reply = client.post(root+'/assistant/chat', headers=headers, json={'message':'谁还没有到集合点？'})
    assert reply.status_code == 200, reply.text
    ended = end_training(exercise)
    archive = client.get(root+'/archive', headers=headers).json()['archive']
    assert archive['data']['score'] == ended['score']
    assert archive['data']['metrics']['arrived'] == 0
    assert archive['data']['unresolved']['unarrived']
    assert archive['data']['conversation_count_at_end'] == 1
    assert archive['data']['origin'] == 'end_transaction'
    assert len(archive['data']['final_state']['residents']) == ended['simulation']['summary']['total']
    assert len(archive['data']['final_state']['tasks']) == len(ended['tasks'])
    assert 'participant_token' not in json.dumps(archive['data'])
    assert digest(json.dumps(archive['data'], sort_keys=True, ensure_ascii=False)) == archive['content_hash']
    doc = client.get('/api/v1/knowledge/documents/'+archive['experience']['id'], headers=headers).json()
    assert doc['versions'][0]['status'] == 'draft'
    assert doc['experience']['kind'] == 'simulation_archive'
    assert doc['experience']['result_kind'] == 'incomplete'
    assert 'predicted' not in doc['experience']
    query = {'query': doc['title'], 'community_id':doc['community_id'], 'scenario':doc['scenario']}
    search = lambda: client.post('/api/v1/knowledge/search', headers=headers, json=query).json()
    assert not any(hit['document_id'] == doc['id'] for hit in search()['hits'])
    publish(client, headers, doc)
    hit = next(hit for hit in search()['hits'] if hit['document_id'] == doc['id'])
    assert hit['experience']['archive_id'] == archive['id']
    assert hit['applicability']['status'] != 'matched'
    again = client.post(root+'/archive', headers=headers).json()['archive']
    assert again['content_hash'] == archive['content_hash'] and again['experience']['id'] == doc['id']


def test_historical_backfill_preserves_score_and_draft_deletion_preserves_archive(exercise):
    client, headers, _, root, *_ = exercise
    original = end_training(exercise)['score']
    old_document = client.get(root+'/archive', headers=headers).json()['archive']['experience']['id']
    assert client.delete('/api/v1/knowledge/documents/'+old_document, headers=headers).status_code == 200
    with operations.SessionLocal() as session:
        record = session.scalar(select(DrillArchive))
        # Isolated fixture simulates an old run without an automatic archive.
        session.delete(record)
        session.commit()
    assert client.get(root+'/archive', headers=headers).json()['archive'] is None
    archive = client.post(root+'/archive', headers=headers).json()['archive']
    assert archive['data']['score'] == original
    assert archive['data']['origin'] == 'historical_reconstruction'
    assert archive['data']['engine_revision'] is None
    # Same deterministic document ID belongs to the same archive in this fixture.
    assert old_document == archive['experience']['id']
    document_id = archive['experience']['id']
    assert client.delete('/api/v1/knowledge/documents/'+document_id, headers=headers).status_code == 200
    remaining = client.post(root+'/archive', headers=headers).json()['archive']
    assert remaining['content_hash'] == archive['content_hash'] and remaining['experience'] is None
    assert client.get(root, headers=headers).json()['score'] == original


def test_archive_failure_rolls_back_end_and_score(exercise, monkeypatch):
    client, headers, demo, root, *_ = exercise
    assert client.patch(root+'/state', headers=headers, json={'action':'start'}).status_code == 200
    def failure(*args, **kwargs):
        raise RuntimeError('archive storage unavailable')
    monkeypatch.setattr('app.services.training_archive.archive_drill', failure)
    with pytest.raises(RuntimeError, match='archive storage unavailable'):
        client.patch(root+'/state', headers=headers, json={'action':'end'})
    with operations.SessionLocal() as session:
        assert session.get(DrillSession, demo['drill_id']).status == 'running'
        assert session.scalar(select(DrillArchive)) is None
    assert client.get(root, headers=headers).json()['score'] is None


def test_chat_pagination_idempotency_clear_and_access_control(exercise):
    client, headers, _, root, *_ = exercise
    path = root+'/assistant/conversation'
    assert client.get(path, headers=headers).json() == {'generation':0, 'items':[], 'next_before':None}
    for index in range(3):
        body = {'message':'道路堵了怎么办？'+str(index), 'request_id':'conversation-'+str(index), 'conversation_generation':0}
        response = client.post(root+'/assistant/chat', headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert client.post(root+'/assistant/chat', headers=headers, json=body).json() == response.json()
    page = client.get(path+'?limit=2', headers=headers).json()
    assert len(page['items']) == 2 and page['next_before'] == 2
    earlier = client.get(path+'?limit=2&before=2', headers=headers).json()
    assert len(earlier['items']) == 1 and earlier['items'][0]['sequence'] == 1
    assert 'token_hash' not in json.dumps(page)
    assert client.post(root+'/assistant/chat', headers=headers, json={**body,'message':'另一个问题'}).status_code == 409
    assert client.delete(path+'?generation=0', headers=headers).json()['generation'] == 1
    assert not client.get(path, headers=headers).json()['items']
    assert client.post(root+'/assistant/chat', headers=headers, json=body).status_code == 409
    assert client.delete(path+'?generation=0', headers=headers).status_code == 409
    app.dependency_overrides[get_current_identity] = lambda: AuthenticatedIdentity('another', '系统管理员', ('system_admin',), 'another')
    try:
        assert client.get(path, headers=headers).status_code == 404
        assert client.delete(path+'?generation=1', headers=headers).status_code == 404
        assert client.get(root+'/archive', headers=headers).status_code == 404
        assert client.post(root+'/archive', headers=headers).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_identity)


def test_inflight_reply_cannot_resurrect_cleared_conversation(exercise):
    client, headers, demo, root, *_ = exercise
    payload = ChatRequest(message='现场情况', request_id='pending-question-001', conversation_generation=0)
    with operations.SessionLocal() as session:
        generation, cached = prepare_request(session, demo['drill_id'], 'admin', payload)
        assert generation == 0 and cached is None
    assert client.delete(root+'/assistant/conversation?generation=0', headers=headers).status_code == 200
    with operations.SessionLocal() as session:
        with pytest.raises(HTTPException) as failure:
            save_exchange(session, demo['drill_id'], 'admin', payload, generation, payload.request_id, {'answer':'late'})
        assert failure.value.status_code == 409
    assert client.get(root+'/assistant/conversation', headers=headers).json()['items'] == []
