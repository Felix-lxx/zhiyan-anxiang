from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrillSession(Base):
    __tablename__ = "drill_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False, index=True)
    scene_version_id: Mapped[str] = mapped_column(ForeignKey("scene_versions.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    time_scale: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    participants: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class DrillEvent(Base):
    __tablename__ = "drill_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class DrillCommand(Base):
    """Authoritative command ledger; domain events remain the immutable evidence stream."""

    __tablename__ = "drill_commands"
    __table_args__ = (UniqueConstraint("drill_session_id", "command_id", name="uq_drill_command_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    command_id: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    command_args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expected_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="submitted", nullable=False)
    label: Mapped[str] = mapped_column(String(200), default="指令已提交", nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="等待服务端校验。", nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    submitted_at_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_at_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    score_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_after_acceptance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)


class DrillStateSnapshot(Base):
    """Recoverable materialized state; immutable events remain the source of truth."""

    __tablename__ = "drill_state_snapshots"
    __table_args__ = (UniqueConstraint("drill_session_id", "state_version", name="uq_drill_snapshot_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    state_version: Mapped[str] = mapped_column(String(64), nullable=False)
    event_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class DrillEngineLease(Base):
    """Database lease preventing multiple application workers from ticking one drill."""

    __tablename__ = "drill_engine_leases"

    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False)


class RobotAgent(Base):
    __tablename__ = "robot_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="巡检广播机器人 R-01", nullable=False)
    state: Mapped[str] = mapped_column(String(40), default="idle", nullable=False)
    battery: Mapped[int] = mapped_column(Integer, default=96, nullable=False)
    x: Mapped[float] = mapped_column(Float, default=18.0, nullable=False)
    y: Mapped[float] = mapped_column(Float, default=53.0, nullable=False)
    current_task: Mapped[str | None] = mapped_column(String(200), nullable=True)
    route: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="等待演练开始", nullable=False)


class DrillScore(Base):
    __tablename__ = "drill_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey("drill_sessions.id", ondelete="CASCADE"), unique=True, nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    recommendations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
