from contextlib import asynccontextmanager
import asyncio
import os
from contextlib import suppress

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, communities, decisions, demo, health, map_objects, operations, road_network, roles, scenes, tasks, assistant
from app.api.routes import account
from app.api.routes import agent
import app.models.tasks  # noqa: F401
from app.core.config import get_settings
from app.core.database import initialize_schema


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialized = initialize_schema()
    if not initialized and settings.app_env != "development":
        raise RuntimeError("数据库初始化失败，停止启动以避免不完整部署。")
    from app.services.engine_scheduler import serve
    worker = asyncio.create_task(serve()) if not os.environ.get("PYTEST_CURRENT_TEST") else None
    from app.services.agent_workflow import serve as serve_agent
    agent_worker = asyncio.create_task(serve_agent()) if not os.environ.get("PYTEST_CURRENT_TEST") else None
    try:
        yield
    finally:
        if agent_worker:
            agent_worker.cancel()
            with suppress(asyncio.CancelledError):
                await agent_worker
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker


app = FastAPI(title=settings.app_name, version="1.0.0-beta", lifespan=lifespan)

@app.middleware("http")
async def security_headers_and_admission(request, call_next):
    from fastapi import HTTPException
    from app.services.connection_security import rate_limit
    path = request.url.path
    limited = path.endswith(("/participant/resolve", "/participant-invite", "/join", "/socket-ticket", "/auth/login", "/auth/refresh"))
    if limited and request.method != "OPTIONS":
        try:
            def check_admission():
                with operations.SessionLocal() as session:
                    # Do not trust arbitrary forwarded IP headers from the public client.
                    subject = request.client.host if request.client else "unknown"
                    rate_limit(session, path.rsplit("/", 1)[-1], subject, 600 if path.endswith("/socket-ticket") else 60)
                    session.commit()
            await asyncio.to_thread(check_admission)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    return response


# Outermost middleware also adds CORS to admission-limit errors.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=(r"^https?://(localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):5173$" if settings.app_env == "development" else None),
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
app.include_router(agent.router, prefix=settings.api_prefix)


@app.websocket("/ws/system")
async def system_socket(websocket: WebSocket) -> None:
    """为后续演练实时事件通道预留的最小可用 WebSocket 端点。"""

    await websocket.accept()
    await websocket.send_json({"type": "system.ready", "message": "实时通道已连接"})
    await websocket.close()
