"""Durable training archives and account-scoped assistant conversations."""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrillArchive(Base):
    __tablename__ = 'drill_archives'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey('drill_sessions.id', ondelete='CASCADE'), unique=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    experience_document_id: Mapped[str | None] = mapped_column(
        ForeignKey('knowledge_documents.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class AssistantConversation(Base):
    __tablename__ = 'assistant_conversations'
    __table_args__ = (UniqueConstraint('drill_session_id', 'owner', name='uq_drill_conversation_owner'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    drill_session_id: Mapped[str] = mapped_column(ForeignKey('drill_sessions.id', ondelete='CASCADE'), index=True)
    owner: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer, default=0)
    next_sequence: Mapped[int] = mapped_column(Integer, default=1)


class AssistantExchange(Base):
    __tablename__ = 'assistant_exchanges'
    __table_args__ = (
        UniqueConstraint('conversation_id', 'generation', 'request_id', name='uq_conversation_request'),
        UniqueConstraint('conversation_id', 'sequence', name='uq_conversation_sequence'),
        Index('ix_conversation_exchange_page', 'conversation_id', 'generation', 'sequence'),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(ForeignKey('assistant_conversations.id', ondelete='CASCADE'))
    generation: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(80))
    request_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(Text)
    reply: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
