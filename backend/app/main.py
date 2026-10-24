import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
import app.models.tasks  # noqa: F401
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.lifespan import create_lifespan
from app.core.origins import DEVELOPMENT_ORIGIN_PATTERN
from app.core.security_logging import configure_security_logging


settings = get_settings()
configure_security_logging()

app = FastAPI(title=settings.app_name, version="1.0.0-beta", lifespan=create_lifespan(settings))

@app.middleware("http")
async def security_headers_and_admission(request, call_next):
    from fastapi import HTTPException
    from app.services.connection_security import rate_limit
    from app.services.command_lock import serialized_command
    path = request.url.path
    limited = path.endswith(("/participant/resolve", "/participant-invite", "/join", "/socket-ticket", "/auth/login", "/auth/refresh"))
    if limited and request.method != "OPTIONS":
        try:
            @serialized_command
            def check_admission():
                with SessionLocal() as session:
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
    allow_origin_regex=(DEVELOPMENT_ORIGIN_PATTERN if settings.app_env == "development" else None),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.websocket("/ws/system")
async def system_socket(websocket: WebSocket) -> None:
    """为后续演练实时事件通道预留的最小可用 WebSocket 端点。"""

    await websocket.accept()
    await websocket.send_json({"type": "system.ready", "message": "实时通道已连接"})
    await websocket.close()
