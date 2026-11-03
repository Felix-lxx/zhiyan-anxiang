"""Bound request bodies before JSON validation allocates a large upload."""
import asyncio
from starlette.responses import JSONResponse


class KnowledgeBodyLimit:
    def __init__(self, app, prefix='/api/v1/knowledge/'):
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith(self.prefix) or scope.get('method') != 'POST':
            return await self.app(scope, receive, send)
        body = bytearray()
        try:
            async with asyncio.timeout(20):
                while True:
                    event = await receive()
                    if event['type'] == 'http.disconnect':
                        return
                    chunk = event.get('body', b'')
                    if len(body) + len(chunk) > 4_300_000:
                        return await JSONResponse({'detail': '知识资料请求超过大小限制。'}, status_code=413)(scope, receive, send)
                    body.extend(chunk)
                    if not event.get('more_body'):
                        break
        except TimeoutError:
            return await JSONResponse({'detail': '资料上传超时，请重试。'}, status_code=408)(scope, receive, send)
        delivered = False

        async def buffered_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()

        await self.app(scope, buffered_receive, send)
