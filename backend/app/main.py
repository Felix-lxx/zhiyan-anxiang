from contextlib import asynccontextmanager
import asyncio
import os
from contextlib import suppress

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, communities, decisions, demo, health, map_objects, operations, road_network, roles, scenes, tasks, assistant
from app.api.routes import account
import app.models.tasks  # noqa: F401
from app.core.config import get_settings
from app.core.database import initialize_schema


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_schema()
    from app.services.engine_scheduler import serve
    worker = asyncio.create_task(serve()) if not os.environ.get("PYTEST_CURRENT_TEST") else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title=settings.app_name, version="1.0.0-beta", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):5173$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(account.router, prefix=settings.api_prefix)
app.include_router(demo.router, prefix=settings.api_prefix)
app.include_router(communities.router, prefix=settings.api_prefix)
app.include_router(map_objects.router, prefix=settings.api_prefix)
app.include_router(road_network.router, prefix=settings.api_prefix)
app.include_router(scenes.router, prefix=settings.api_prefix)
app.include_router(decisions.router, prefix=settings.api_prefix)
app.include_router(tasks.router, prefix=settings.api_prefix)
app.include_router(operations.router, prefix=settings.api_prefix)
app.include_router(roles.router, prefix=settings.api_prefix)
app.include_router(assistant.router, prefix=settings.api_prefix)


@app.websocket("/ws/system")
async def system_socket(websocket: WebSocket) -> None:
    """为后续演练实时事件通道预留的最小可用 WebSocket 端点。"""

    await websocket.accept()
    await websocket.send_json({"type": "system.ready", "message": "实时通道已连接"})
    await websocket.close()
