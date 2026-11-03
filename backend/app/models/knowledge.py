"""Versioned knowledge and immutable retrieval evidence, separate from drill facts."""
from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class KnowledgeDocument(Base):
    __tablename__ = 'knowledge_documents'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str | None] = mapped_column(String(64), index=True)
    community_id: Mapped[str | None] = mapped_column(ForeignKey('communities.id'), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(40))
    scenario: Mapped[str] = mapped_column(String(32), default='all', index=True)
    source_url: Mapped[str] = mapped_column(String(1200), default='')
    publisher: Mapped[str] = mapped_column(String(200), default='')
    builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class KnowledgeVersion(Base):
    __tablename__ = 'knowledge_versions'
    __table_args__ = (UniqueConstraint('document_id', 'number'),
        Index('uq_knowledge_published_document', 'document_id', unique=True,
              sqlite_where=text("status = 'published'"), postgresql_where=text("status = 'published'")))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default='draft', index=True)
    filename: Mapped[str] = mapped_column(String(200), default='')
    content_hash: Mapped[str] = mapped_column(String(64))
    extraction: Mapped[str] = mapped_column(String(40), default='text')
    pages: Mapped[list] = mapped_column(JSON, default=list)
    failure: Mapped[str] = mapped_column(Text, default='')
    reviewer: Mapped[str | None] = mapped_column(String(64))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class KnowledgeChunk(Base):
    __tablename__ = 'knowledge_chunks'
    __table_args__ = (UniqueConstraint('version_id', 'ordinal'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    version_id: Mapped[str] = mapped_column(ForeignKey('knowledge_versions.id', ondelete='CASCADE'), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[list | None] = mapped_column(JSON)


class KnowledgeRetrieval(Base):
    __tablename__ = 'knowledge_retrievals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    community_id: Mapped[str | None] = mapped_column(ForeignKey('communities.id'))
    drill_id: Mapped[str | None] = mapped_column(ForeignKey('drill_sessions.id'))
    query_hash: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(40))
    notice: Mapped[str] = mapped_column(Text, default='')
    hits: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class KnowledgeExperience(Base):
    """Frozen observation provenance, independent of editable knowledge prose."""
    __tablename__ = 'knowledge_experiences'
    __table_args__ = (UniqueConstraint('owner', 'decision_check_id', name='uq_knowledge_experience_observation'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    # IDs and facts survive source archival; opening the original source still
    # goes through the drill's normal existence and ownership checks.
    decision_check_id: Mapped[str] = mapped_column(String(36), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), unique=True)
    basis: Mapped[dict] = mapped_column(JSON)
    basis_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
