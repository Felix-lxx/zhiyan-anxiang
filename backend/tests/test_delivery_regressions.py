"""Regressions exercised with the running API's non-expiring session settings."""
from datetime import UTC, datetime

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import decode_access_claims
from app.services.demo_experience import ensure_demo_experience
from app.services.scenes import update_scene_parameters


def test_access_tokens_require_expiration():
    settings = get_settings()
    for claims in ({"sub": "admin"}, {"sub": "admin", "iat": datetime.now(UTC)}):
        token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_claims(token)


def test_socket_and_participant_credentials_are_redacted_in_formatted_logs():
    import logging
    from app.core.security_logging import CredentialRedactionFilter
    record = logging.LogRecord('uvicorn.error', logging.INFO, '', 0, 'WebSocket %s',
                               ('/api/v1/ws/drills/test?ticket=secret-one&protocol=3&code=secret-two',), None)
    assert CredentialRedactionFilter().filter(record)
    assert 'secret-' not in record.getMessage()
    assert 'protocol=3' in record.getMessage()
    from uvicorn.logging import AccessFormatter
    access = logging.LogRecord('uvicorn.access', logging.INFO, '', 0, '%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1:1234', 'GET', '/participant/resolve?code=secret-three', '1.1', 200), None)
    CredentialRedactionFilter().filter(access)
    assert 'secret-three' not in AccessFormatter().format(access)


def test_auth_rejects_untrusted_browser_origin_before_changing_cookie(client):
    login = client.post('/api/v1/auth/login', headers={'Origin': 'https://untrusted.example'},
                        json={'username': 'admin', 'password': 'Zhiyan@2026'})
    assert login.status_code == 403
    assert 'set-cookie' not in login.headers
    assert client.post('/api/v1/auth/refresh?optional=true', headers={'Origin': 'null'}).status_code == 403
    assert client.post('/api/v1/auth/refresh?optional=true', headers={'Origin': 'http://127.0.0.1:5173'}).status_code == 204


def test_repeated_demo_and_draft_keep_current_tasks(client):
    from app.api.routes.operations import SessionLocal
    with SessionLocal() as session:
        # Test fixtures expire on commit by default; deployment does not.
        session.expire_on_commit = False
        community, scene, _ = ensure_demo_experience(session, 'admin')
        original_id = scene.versions[-1].id
        parameters = {**scene.versions[-1].parameters, 'resident_count': 24}
        scene = update_scene_parameters(session, scene=scene, parameters=parameters)
        assert scene.versions[-1].id != original_id
        assert scene.versions[-1].parameters['resident_count'] == 24
        from app.services.scenario_tasks import missing_tasks
        assert not missing_tasks(session, scene.versions[-1], 'night_charging_shed_fire')
        # Existing training settings must survive the entry action.
        _, scene, repaired_drill = ensure_demo_experience(session, 'admin')
        assert scene.versions[-1].parameters['resident_count'] == 24
        assert not missing_tasks(session, scene.versions[-1], 'night_charging_shed_fire')
        from app.services.exercise_world import frozen_world
        world = frozen_world(session, repaired_drill)
        assert len(world['residents']) == 24
        assert len(world['tasks']) == 3
        version_id = scene.versions[-1].id
        _, scene, _ = ensure_demo_experience(session, 'admin')
        assert scene.versions[-1].id == version_id
