"""Authenticated, bounded audio intake. Audio is never written to disk."""
import asyncio
from contextlib import suppress
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.config import get_settings
from app.services.speech import MAX_AUDIO_BYTES, SpeechError, speech_status, transcribe

router = APIRouter(tags=['speech'])
_guard = Lock()
_active: set[str] = set()


@router.get('/speech/status')
def status(identity: AuthenticatedIdentity = Depends(get_current_identity)):
    return speech_status(get_settings())


@router.post('/speech/transcribe')
async def recognize(request: Request, identity: AuthenticatedIdentity = Depends(get_current_identity)):
    settings = get_settings()
    if not speech_status(settings)['configured']:
        raise HTTPException(503, '语音听写尚未配置，请联系管理员。')
    if request.headers.get('content-type', '').split(';')[0].strip() != 'audio/pcm':
        raise HTTPException(415, '请使用平台录音入口提交 PCM 音频。')
    with _guard:
        if identity.username in _active or len(_active) >= 3:
            raise HTTPException(429, '语音服务正在处理录音，请稍后重试。')
        _active.add(identity.username)
    try:
        pcm = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    if len(pcm) + len(chunk) > MAX_AUDIO_BYTES:
                        raise HTTPException(413, '录音超过 30 秒，请缩短后重试。')
                    pcm.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, '录音上传超时，请重试。') from None
        if len(pcm) < 8000 or len(pcm) % 2:
            raise HTTPException(422, '录音太短或格式不正确，请重新录音。')
        try:
            async def disconnected():
                while True:
                    message = await request.receive()
                    if message['type'] == 'http.disconnect':
                        return
                    await asyncio.sleep(.25)

            recognition = asyncio.create_task(transcribe(settings, bytes(pcm)))
            disconnect = asyncio.create_task(disconnected())
            try:
                done, _ = await asyncio.wait((recognition, disconnect), return_when=asyncio.FIRST_COMPLETED)
                if recognition not in done:
                    raise HTTPException(499, '语音识别已取消。')
                text = recognition.result()
            finally:
                for task in (recognition, disconnect):
                    task.cancel()
                for task in (recognition, disconnect):
                    with suppress(asyncio.CancelledError, Exception):
                        await task
        except SpeechError as exc:
            raise HTTPException(502, str(exc)) from None
        return {'text': text, 'provider': 'xfyun_iat_v1', 'duration_seconds': round(len(pcm) / 32000, 2)}
    finally:
        with _guard:
            _active.discard(identity.username)
