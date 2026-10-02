from __future__ import annotations

from threading import BoundedSemaphore, Lock
from typing import Any, Literal
from uuid import uuid4
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.api.routes import operations
from app.core.config import get_settings
from app.core.database import get_db
from app.models.domain import Scene
from app.services.scene_assistant import build_context, offline_reply, provider_status, call_model, DISCLAIMER

router = APIRouter(tags=["scene assistant"])
_slots = BoundedSemaphore(4)
_guard = Lock()
_active: set[str] = set()
logger = logging.getLogger(__name__)


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class SelectionContext(BaseModel):
    """Small, user-visible focus context from the director UI.

    It is supporting evidence only.  The authoritative drill snapshot is still
    loaded on the server and the model is never allowed to execute from it.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["resident", "road", "robot", "object", "command", "score", "replay"]
    id: str | None = Field(default=None, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    type: str | None = Field(default=None, max_length=120)
    detail: str | None = Field(default=None, max_length=600)
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=12)
    at_seconds: int | None = Field(default=None, ge=0)
    use_model: bool = False
    selection_context: SelectionContext | None = None

    @field_validator("history")
    @classmethod
    def bounded_history(cls, value: list[Turn]):
        if sum(len(turn.content) for turn in value) > 24000:
            raise ValueError("对话过长，请开始新的对话。")
        return value

    @field_validator("message")
    @classmethod
    def nonblank(cls, value: str):
        if not value.strip():
            raise ValueError("请输入问题。")
        return value.strip()


@router.get("/assistant/status")
def assistant_status(identity: AuthenticatedIdentity = Depends(get_current_identity)):
    return provider_status(get_settings())


@router.post("/drills/{drill_id}/assistant/chat")
def chat(drill_id: str, payload: ChatRequest, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    drill = operations.require_drill(session, drill_id, identity.username)
    scene = session.get(Scene, drill.scene_id)
    historical = payload.at_seconds is not None
    # Unlike the regular polling endpoint, this never advances or mutates the engine.
    if historical:
        state = operations.replay_drill(drill_id, payload.at_seconds, identity, session)
        data = {**state, "id": drill.id, "name": drill.name, "status": "replay", "elapsed_seconds": state["at_seconds"]}
    else:
        data = operations.snapshot(session, drill)
    selection_context: dict[str, Any] | None = payload.selection_context.model_dump(exclude_none=True) if payload.selection_context else None
    context = build_context(data, scene.name, historical, payload.message, selection_context)
    question = payload.message
    if len(question) < 10 and any(w in question for w in ("为什么", "怎么办", "然后呢", "继续")):
        previous = next((t.content for t in reversed(payload.history) if t.role == "user"), "")
        question = previous + "；" + question
    answer, actions = offline_reply(question, context)
    settings = get_settings()
    status = provider_status(settings)
    mode, notice = "offline", "离线规则解读，未调用大模型。"
    if payload.use_model and status["configured"]:
        with _guard:
            if identity.username in _active:
                raise HTTPException(429, "上一条模型请求仍在处理，请稍后再试。")
            _active.add(identity.username)
        acquired = _slots.acquire(blocking=False)
        try:
            if not acquired:
                raise HTTPException(429, "模型服务繁忙，请稍后重试或使用离线解读。")
            try:
                answer = call_model(settings, payload.message, [t.model_dump() for t in payload.history], context)
                mode, notice = "model", "模型基于本轮快照生成，可能有误；请核对下方数据依据。"
            except Exception as error:
                # Never expose upstream request URLs, API keys or provider error bodies.
                logger.warning("Scene assistant model request failed: %s", type(error).__name__)
                notice = "模型暂不可用，已降级为离线解读。请管理员检查模型地址、密钥和服务日志。"
        finally:
            if acquired:
                _slots.release()
            with _guard:
                _active.discard(identity.username)
    elif payload.use_model:
        notice = "尚未完成模型配置，已使用离线解读。"
    return {"id": str(uuid4()), "mode": mode, "model": settings.assistant_model if mode == "model" else None,
            "answer": answer, "notice": notice, "disclaimer": DISCLAIMER,
            "context": {k: context[k] for k in ("drill_id", "scene_name", "drill_name", "at_seconds", "historical", "counts", "selection")},
            "sources": context["sources"], "actions": actions,
            "suggestions": ["现在下一步应该做什么？", "谁还没有到集合点？", "机器人为什么没动？", "道路拥堵应该怎么处理？", "如何从关键决定前重做？"]}
