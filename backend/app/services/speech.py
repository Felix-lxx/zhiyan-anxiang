"""Server-only XFYun IAT V1 signing, paced PCM transfer and corrected transcripts."""
import asyncio
import base64
import hashlib
import hmac
import json
from contextlib import suppress
from datetime import UTC, datetime
from email.utils import format_datetime
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from app.core.config import Settings

MAX_AUDIO_SECONDS = 30
MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * 16000 * 2
HOST = 'iat.xf-yun.com'


class SpeechError(Exception):
    """Safe public error; never includes provider URLs or credentials."""


def speech_status(settings: Settings) -> dict:
    configured = settings.speech_provider == 'xfyun_iat_v1' and bool(
        settings.speech_app_id and settings.speech_api_key.get_secret_value()
        and settings.speech_api_secret.get_secret_value())
    return {'configured': configured, 'provider': '讯飞语音听写 V1.0' if configured else None,
            'max_seconds': MAX_AUDIO_SECONDS}


def signed_url(settings: Settings, now: datetime | None = None) -> str:
    date = format_datetime((now or datetime.now(UTC)).astimezone(UTC), usegmt=True)
    original = f'host: {HOST}\ndate: {date}\nGET /v1 HTTP/1.1'
    signature = base64.b64encode(hmac.new(settings.speech_api_secret.get_secret_value().encode(),
                                         original.encode(), hashlib.sha256).digest()).decode()
    authorization = (f'api_key="{settings.speech_api_key.get_secret_value()}", '
                     'algorithm="hmac-sha256", headers="host date request-line", '
                     f'signature="{signature}"')
    return f'wss://{HOST}/v1?' + urlencode({'host': HOST, 'date': date,
        'authorization': base64.b64encode(authorization.encode()).decode()})


class Transcript:
    def __init__(self):
        self.parts: dict[int, str] = {}

    def accept(self, message: dict) -> bool:
        header = message.get('header', {})
        code = header.get('code', 0)
        if code != 0:
            raise SpeechError(f'讯飞听写失败（错误码 {int(code)}），请检查服务开通、额度和密钥。')
        result = message.get('payload', {}).get('result', {})
        if result.get('text'):
            data = json.loads(base64.b64decode(result['text'], validate=True))
            if data.get('ret', 0) != 0:
                raise SpeechError('讯飞未能完成本次听写，请重试。')
            if data.get('pgs') == 'rpl':
                start, end = data['rg']
                for sn in list(self.parts):
                    if start <= sn <= end:
                        del self.parts[sn]
            text = ''.join(word.get('cw', [{}])[0].get('w', '') for word in data.get('ws', []) if word.get('cw'))
            self.parts[int(data['sn'])] = text
        return header.get('status') == 2 or result.get('status') == 2

    def text(self) -> str:
        return ''.join(self.parts[key] for key in sorted(self.parts)).strip()


async def transcribe(settings: Settings, pcm: bytes) -> str:
    if not speech_status(settings)['configured']:
        raise SpeechError('语音听写尚未配置。')
    if not 8000 <= len(pcm) <= MAX_AUDIO_BYTES or len(pcm) % 2:
        raise SpeechError('请提供 0.25–30 秒、16kHz 单声道的 PCM 录音。')

    async def send_audio(socket):
        for index, offset in enumerate(range(0, len(pcm), 1280)):
            status = 0 if index == 0 else 1
            frame = {'header': {'app_id': settings.speech_app_id, 'status': status},
                     'payload': {'audio': {'encoding': 'raw', 'sample_rate': 16000, 'channels': 1,
                         'bit_depth': 16, 'seq': index + 1, 'status': status,
                         'audio': base64.b64encode(pcm[offset:offset + 1280]).decode()}}}
            if index == 0:
                frame['parameter'] = {'iat': {'domain': 'slm', 'language': 'zh_cn', 'accent': 'mandarin',
                    'dwa': 'wpgs', 'result': {'encoding': 'utf8', 'compress': 'raw', 'format': 'json'}}}
            await socket.send(json.dumps(frame))
            await asyncio.sleep(0.04)
        await socket.send(json.dumps({'header': {'app_id': settings.speech_app_id, 'status': 2},
            'payload': {'audio': {'encoding': 'raw', 'sample_rate': 16000, 'channels': 1, 'bit_depth': 16,
                                 'seq': (len(pcm) + 1279) // 1280 + 1, 'status': 2, 'audio': ''}}}))

    async def receive(socket):
        transcript = Transcript()
        async for raw in socket:
            if transcript.accept(json.loads(raw)):
                text = transcript.text()
                if not text:
                    raise SpeechError('没有识别到说话内容，请靠近麦克风后重试。')
                if len(text) > 4000:
                    raise SpeechError('识别文字过长，请缩短录音。')
                return text
        raise SpeechError('语音连接提前结束，请重试。')

    try:
        async with asyncio.timeout(50):
            # Explicit fixed provider; do not expose signed URLs to browsers or logs.
            async with connect(signed_url(settings), open_timeout=10, close_timeout=2,
                               max_size=256_000, proxy=None) as socket:
                sender = asyncio.create_task(send_audio(socket))
                receiver = asyncio.create_task(receive(socket))
                try:
                    done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
                    if receiver in done:
                        return receiver.result()
                    await sender
                    return await receiver
                finally:
                    for task in (sender, receiver):
                        task.cancel()
                    for task in (sender, receiver):
                        with suppress(asyncio.CancelledError, Exception):
                            await task
    except SpeechError:
        raise
    except TimeoutError:
        raise SpeechError('语音听写超时，请检查网络后重试。') from None
    except Exception:
        raise SpeechError('无法连接讯飞听写，请检查服务权限、密钥和后端网络。') from None
