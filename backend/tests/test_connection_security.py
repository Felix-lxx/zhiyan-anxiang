from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.api.routes import operations
from app.core.config import Settings
from app.models.operations import ParticipantInvitation
from app.services.connection_security import rate_limit
from test_exercise_world import exercise


def test_production_rejects_defaults_and_permissive_origins():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", jwt_secret="x"*40,
            bootstrap_admin_password="Unique-Secure-Initial-Password", cors_origins="*")
    settings = Settings(_env_file=None, app_env="production", jwt_secret="private-random-key-for-config-check-123456789",
        bootstrap_admin_password="Unique-Secure-Initial-Password", cors_origins="https://training.example.org")
    assert settings.cors_origin_list == ["https://training.example.org"]


def test_invitation_hash_ticket_reuse_revocation_and_participant_logout(exercise):
    client, headers, demo, root, public, code, *_ = exercise
    assert len(code) == 32
    assert client.get(public, params={"code": demo["drill_id"].replace("-", "")[-6:]}).status_code == 404
    assert client.get('/api/v1/participant/resolve', params={"code": code.lower()}).json()["drill_id"] == demo["drill_id"]
    with operations.SessionLocal() as session:
        stored = session.scalar(select(ParticipantInvitation))
        assert stored.code_hash != code and len(stored.code_hash) == 64
    member = client.post(public+'/join', params={"code":code}, json={"role":"物业/网格员", "display_name":"测试值守"}).json()
    leave = client.post(public+'/leave', params={"code":code}, json={"participant_token":member["token"]})
    assert leave.status_code == 200
    assert client.post(public+'/heartbeat', params={"code":code}, json={"participant_token":member["token"]}).status_code == 403
    ticket = client.post(public+'/socket-ticket', json={"code":code}).json()["ticket"]
    url = f"/api/v1/ws/drills/{demo['drill_id']}?ticket={ticket}&protocol=3"
    with client.websocket_connect(url) as socket:
        assert socket.receive_json()["type"] == "drill.snapshot"
        assert client.delete(root+'/participant-invite', headers=headers).status_code == 204
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(url): pass
    assert client.get(public, params={"code":code}).status_code == 404
    assert client.post(public+'/socket-ticket', json={"code":code}).status_code == 404
    replacement = client.post(root+'/participant-invite', headers=headers).json()["code"]
    assert replacement != code
    assert client.get(public, params={"code":replacement}).status_code == 200
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/ws/drills/{demo['drill_id']}?token={headers['Authorization'][7:]}"): pass


def test_expired_invite_and_atomic_admission_limit(exercise):
    client, headers, _, root, public, code, *_ = exercise
    with operations.SessionLocal() as session:
        invite = session.scalar(select(ParticipantInvitation))
        invite.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert client.get(public, params={"code":code}).status_code == 404
    with operations.SessionLocal() as session:
        rate_limit(session, "test", "client", limit=2)
        session.commit()
        rate_limit(session, "test", "client", limit=2)
        session.commit()
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            rate_limit(session, "test", "client", limit=2)
        assert error.value.status_code == 429
    ticket = client.post(root+'/socket-ticket', headers=headers).json()["ticket"]
    with client.websocket_connect(f"/api/v1/ws/drills/{root.rsplit('/',1)[-1]}?ticket={ticket}&protocol=3") as socket:
        assert socket.receive_json()["type"] == "drill.snapshot"
        client.post('/api/v1/auth/logout', headers=headers)
        with pytest.raises(WebSocketDisconnect): socket.receive_json()


def test_staff_responsibility_is_exclusive_and_logged(exercise):
    client, headers, _, root, public, code, *_ = exercise
    member = client.post(public+'/join', params={"code":code}, json={"role":"物业/网格员", "display_name":"物业甲"}).json()
    result = client.post(root+'/staff/escort-1/binding', headers=headers, json={"participant_id":member["participant_id"]})
    assert result.status_code == 200, result.text
    staff = result.json()["simulation"]["environment"]["response_staff"]
    assert staff[0]["responsible"] == "物业甲"
    assert result.json()["events"][0]["event_type"] == "staff.bound"
    assert client.post(root+'/staff/escort-2/binding', headers=headers, json={"participant_id":member["participant_id"]}).status_code == 409
    assert client.post(root+'/staff/escort-1/binding', headers=headers, json={"participant_id":None}).status_code == 200
