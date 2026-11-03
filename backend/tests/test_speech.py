import asyncio
import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException

from app.core.config import Settings, get_settings
from app.services import speech


def settings():
    return Settings(_env_file=None, speech_provider='xfyun_iat_v1', speech_app_id='test-app',
                    speech_api_key='test-key', speech_api_secret='test-secret')


def packet(sn, text, **extra):
    data = {'sn': sn, 'ws': [{'cw': [{'w': text}]}], **extra}
    return {'header': {'code': 0, 'status': 1}, 'payload': {'result': {
        'text': base64.b64encode(json.dumps(data).encode()).decode(), 'status': 1}}}


def test_signature_uses_provider_host_date_and_request_line():
    url = speech.signed_url(settings(), datetime(2026, 11, 2, tzinfo=UTC))
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert parts.scheme == 'wss' and parts.hostname == 'iat.xf-yun.com' and parts.path == '/v1'
    original = f"host: iat.xf-yun.com\ndate: {query['date'][0]}\nGET /v1 HTTP/1.1"
    signature = base64.b64encode(hmac.new(b'test-secret', original.encode(), hashlib.sha256).digest()).decode()
    assert f'signature="{signature}"' in base64.b64decode(query['authorization'][0]).decode()
    assert 'test-secret' not in url


def test_replacements_remove_superseded_segments_and_provider_errors_fail():
    transcript = speech.Transcript()
    transcript.accept(packet(1, '三号'))
    transcript.accept(packet(2, '老楼'))
    transcript.accept(packet(3, '三号楼', pgs='rpl', rg=[1, 2]))
    assert transcript.text() == '三号楼'
    with pytest.raises(speech.SpeechError):
        transcript.accept({'header': {'code': 10105, 'message': 'do not disclose upstream body'}})


def test_pcm_frames_and_final_provider_result(monkeypatch):
    class Socket:
        def __init__(self):
            self.frames = []
            self.ended = asyncio.Event()

        async def send(self, raw):
            frame = json.loads(raw)
            self.frames.append(frame)
            if frame['header']['status'] == 2:
                self.ended.set()

        def __aiter__(self):
            async def messages():
                await self.ended.wait()
                yield json.dumps(packet(1, '请检查三号楼。'))
                yield json.dumps({'header': {'code': 0, 'status': 2}})
            return messages()

    class Connection:
        async def __aenter__(self):
            self.socket = Socket()
            return self.socket

        async def __aexit__(self, *args):
            return False

    connection = Connection()
    monkeypatch.setattr(speech, 'connect', lambda *args, **kwargs: connection)
    pcm = bytes(8960)
    assert asyncio.run(speech.transcribe(settings(), pcm)) == '请检查三号楼。'
    frames = connection.socket.frames
    assert frames[0]['parameter']['iat']['domain'] == 'slm'
    assert frames[0]['header']['status'] == 0 and frames[-1]['header']['status'] == 2
    assert frames[-1]['payload']['audio']['audio'] == ''
    assert b''.join(base64.b64decode(f['payload']['audio']['audio']) for f in frames) == pcm
    assert [f['payload']['audio']['seq'] for f in frames] == list(range(1, len(frames) + 1))


def test_audio_endpoint_requires_auth_limits_payload_and_preserves_text(client, monkeypatch):
    monkeypatch.setattr('app.api.routes.speech.get_settings', settings)
    called = []

    async def recognize(config, pcm):
        called.append(pcm)
        return '先查看现场，再安排护送。'

    monkeypatch.setattr('app.api.routes.speech.transcribe', recognize)
    assert client.get('/api/v1/speech/status').status_code == 401
    token = client.post('/api/v1/auth/login', json={
        'username': 'admin', 'password': get_settings().bootstrap_admin_password}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    state = client.get('/api/v1/speech/status', headers=headers).json()
    assert state['configured'] and 'test-secret' not in json.dumps(state)
    invalid = client.post('/api/v1/speech/transcribe', headers=headers, content=b'not-pcm')
    assert invalid.status_code == 415 and not called
    headers['Content-Type'] = 'audio/pcm'
    too_big = client.post('/api/v1/speech/transcribe', headers=headers, content=bytes(speech.MAX_AUDIO_BYTES + 2))
    assert too_big.status_code == 413 and not called
    short = client.post('/api/v1/speech/transcribe', headers=headers, content=bytes(20))
    assert short.status_code == 422 and not called
    result = client.post('/api/v1/speech/transcribe', headers=headers, content=bytes(16000))
    assert result.status_code == 200 and result.json()['text'] == '先查看现场，再安排护送。'
    assert called == [bytes(16000)]


def test_disconnected_browser_cancels_provider_task_and_releases_slot(monkeypatch):
    from app.api.routes import speech as route
    monkeypatch.setattr(route, 'get_settings', settings)
    cancelled = []

    async def slow(config, pcm):
        try:
            await asyncio.sleep(100)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(route, 'transcribe', slow)

    class Request:
        headers = {'content-type': 'audio/pcm'}

        async def stream(self):
            yield bytes(16000)

        async def receive(self):
            await asyncio.sleep(.01)
            return {'type': 'http.disconnect'}

    with pytest.raises(HTTPException) as exc:
        asyncio.run(route.recognize(Request(), SimpleNamespace(username='cancel-test')))
    assert exc.value.status_code == 499
    assert cancelled and 'cancel-test' not in route._active
