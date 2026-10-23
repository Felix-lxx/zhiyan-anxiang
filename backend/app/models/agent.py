"""Durable goal workflows; domain commands remain the only writers of the drill."""
from datetime import UTC, datetime
from uuid import uuid4
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("drill_session_id", "request_id", name="uq_agent_run_request"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), index=True)
    request_id: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(64))
    goal: Mapped[str] = mapped_column(Text)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval", index=True)
    reason: Mapped[str] = mapped_column(Text, default="方案尚未执行")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_candidate: Mapped[str | None] = mapped_column(String(40), nullable=True)
    observed_sequence: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    planner: Mapped[str] = mapped_column(String(32), default="local")
    planner_notice: Mapped[str] = mapped_column(Text, default="")
    execution_epoch: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    elapsed_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AgentDecisionCheck(Base):
    """One durable observation per approval, independent of workflow completion."""
    __tablename__ = "agent_decision_checks"
    __table_args__ = (UniqueConstraint("run_id", "revision", name="uq_agent_decision_check"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    due_seconds: Mapped[int] = mapped_column(Integer)
    basis: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AgentResourceClaim(Base):
    """One durable owner per drill resource; process leases never grant ownership."""
    __tablename__ = "agent_resource_claims"
    __table_args__ = (UniqueConstraint("drill_session_id", "resource_key", name="uq_agent_resource_owner"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), index=True)
    resource_key: Mapped[str] = mapped_column(String(100))
    resource_name: Mapped[str] = mapped_column(String(160))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquired_at_seconds: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
