"""Owned document lifecycle and published knowledge retrieval."""
from datetime import UTC, datetime
import json
import subprocess
import sys
import time
from threading import BoundedSemaphore
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, or_, delete
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeRetrieval, KnowledgeExperience
from app.services.knowledge import (add_version, document_payload, require_community,
    require_document, retrieve, seed_knowledge)
from app.services.knowledge_ingestion import MAX_TEXT

router = APIRouter(prefix='/knowledge', tags=['knowledge'])
_extraction_slots = BoundedSemaphore(2)


class Draft(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(default='', max_length=MAX_TEXT)
    community_id: str | None = None
    scenario: Literal['all', 'kitchen_fire', 'charging_shed'] = 'all'
    category: Literal['community_plan', 'equipment', 'experience', 'reference'] = 'community_plan'
    source_url: str = Field(default='', max_length=1200)
    publisher: str = Field(default='', max_length=200)
    filename: str = Field(default='', max_length=200)
    file_base64: str = Field(default='', max_length=4_194_304)
    valid_until: datetime | None = None

    @field_validator('valid_until')
    @classmethod
    def aware_expiry(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('有效截止时间必须带时区。')
        return value

    @field_validator('source_url')
    @classmethod
    def safe_link(cls, value):
        if value:
            url = urlsplit(value)
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                raise ValueError('来源地址需为不带账号的 HTTPS 链接。')
        return value

    @field_validator('title')
    @classmethod
    def meaningful_title(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('资料名称至少需要两个有效字符。')
        return value


class Action(BaseModel):
    action: Literal['review', 'publish', 'withdraw']
    version_id: str


class Search(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    community_id: str | None = None
    scenario: Literal['all', 'kitchen_fire', 'charging_shed'] = 'all'
    semantic: bool = False


class ExperienceCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: str = Field(min_length=1, max_length=36)
    revision: int = Field(ge=1)


@router.post('/experiences')
def create_experience(payload: ExperienceCreate, identity: AuthenticatedIdentity = Depends(get_current_identity),
                      session: Session = Depends(get_db)):
    from app.services.knowledge_experience import draft_from_outcome
    return draft_from_outcome(session, payload.run_id, payload.revision, identity)


def parse_content(payload):
    if payload.file_base64:
        if not _extraction_slots.acquire(blocking=False):
            return [], 'file', '文件解析繁忙，请稍后修订并重新提交。'
        try:
            # Parse outside the API process; fixed executable/module, no shell,
            # no files or remote document fetches. Hard time limit includes PDF parsing.
            result = subprocess.run([sys.executable, '-m', 'app.services.knowledge_worker'],
                input=json.dumps({'filename': payload.filename, 'data': payload.file_base64}),
                text=True, encoding='utf-8', capture_output=True, timeout=15)
            data = json.loads(result.stdout)
            if data.get('error'):
                return [], 'file', data['error']
            return data['pages'], data['extraction'], ''
        except Exception:
            return [], 'file', '文件解析失败或超过 15 秒，请转换为文本后重试。'
        finally:
            _extraction_slots.release()
    text = payload.content.strip()
    if len(text) < 20:
        return [], 'text', '资料至少需要 20 字有效正文。'
    return [('正文', text)], 'text', ''


@router.get('/status')
def status(identity: AuthenticatedIdentity = Depends(get_current_identity)):
    from app.services.knowledge_vectors import configured
    return {'embedding_configured': configured(), 'max_file_bytes': 3 * 1024 * 1024,
            'formats': ['txt', 'md', 'docx', 'pdf'], 'default_method': 'keyword'}


@router.get('/documents')
def list_documents(community_id: str | None = None, scenario: str = 'all',
                   page: int = Query(1, ge=1), identity: AuthenticatedIdentity = Depends(get_current_identity),
                   session: Session = Depends(get_db)):
    require_community(session, community_id, identity.username)
    seed_knowledge(session)
    statement = select(KnowledgeDocument).where(or_(KnowledgeDocument.builtin.is_(True),
        KnowledgeDocument.owner == identity.username), or_(KnowledgeDocument.community_id.is_(None),
        KnowledgeDocument.community_id == community_id))
    if scenario != 'all':
        statement = statement.where(KnowledgeDocument.scenario.in_(['all', scenario]))
    from sqlalchemy import func
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    documents = session.scalars(statement.order_by(KnowledgeDocument.created_at.desc(), KnowledgeDocument.id)
                                 .offset((page - 1) * 30).limit(30))
    return {'items': [document_payload(session, d) for d in documents], 'total': total, 'page': page}


@router.get('/documents/{document_id}')
def detail(document_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity),
           session: Session = Depends(get_db)):
    return document_payload(session, require_document(session, document_id, identity.username), detail=True)


@router.post('/documents', status_code=201)
def create(payload: Draft, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    require_community(session, payload.community_id, identity.username)
    pages, extraction, failure = parse_content(payload)
    document = KnowledgeDocument(owner=identity.username, title=payload.title.strip(), scenario=payload.scenario,
        category=payload.category, source_url=payload.source_url, publisher=payload.publisher.strip(), community_id=payload.community_id)
    session.add(document)
    session.flush()
    add_version(session, document, pages, payload.filename, extraction, failure, payload.valid_until)
    session.commit()
    return document_payload(session, document, detail=True)


@router.post('/documents/{document_id}/versions', status_code=201)
def revision(document_id: str, payload: Draft, identity: AuthenticatedIdentity = Depends(get_current_identity),
             session: Session = Depends(get_db)):
    document = require_document(session, document_id, identity.username, write=True)
    if payload.community_id != document.community_id or payload.scenario != document.scenario:
        raise HTTPException(409, '修订必须保留资料原适用范围；更换范围请创建新资料。')
    if (payload.title, payload.publisher, payload.source_url, payload.category) != (
            document.title, document.publisher, document.source_url, document.category):
        raise HTTPException(409, '资料修订保留原来源和类别；更换这些信息请创建新资料。')
    pages, extraction, failure = parse_content(payload)
    # Serialize version allocation; the unique constraint is a second guard.
    session.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.id == document_id).with_for_update())
    try:
        add_version(session, document, pages, payload.filename, extraction, failure, payload.valid_until)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, '资料已被同时修订，请刷新后重新保存。') from None
    return document_payload(session, document, detail=True)


@router.delete('/documents/{document_id}')
def remove_draft(document_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity),
                 session: Session = Depends(get_db)):
    document = require_document(session, document_id, identity.username, write=True)
    versions = list(session.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == document_id)))
    if any(v.status not in {'draft', 'review', 'failed'} for v in versions):
        raise HTTPException(409, '已发布过的资料保留审计记录，请停用当前版本。')
    ids = [v.id for v in versions]
    session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.version_id.in_(ids)))
    session.execute(delete(KnowledgeVersion).where(KnowledgeVersion.document_id == document_id))
    session.execute(delete(KnowledgeExperience).where(KnowledgeExperience.document_id == document_id))
    from sqlalchemy import update
    from app.models.training import DrillArchive
    session.execute(update(DrillArchive).where(DrillArchive.experience_document_id == document_id)
                    .values(experience_document_id=None))
    session.delete(document)
    session.commit()
    return {'deleted': True}


@router.post('/documents/{document_id}/actions')
def transition(document_id: str, payload: Action, identity: AuthenticatedIdentity = Depends(get_current_identity),
               session: Session = Depends(get_db)):
    document = require_document(session, document_id, identity.username, write=True)
    session.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.id == document_id).with_for_update())
    version = session.get(KnowledgeVersion, payload.version_id)
    if not version or version.document_id != document_id:
        raise HTTPException(404, '未找到该资料版本。')
    count = session.scalar(select(KnowledgeChunk.id).where(KnowledgeChunk.version_id == version.id).limit(1))
    if payload.action == 'review':
        if version.status != 'draft' or not count:
            raise HTTPException(409, '仅有效草稿可提交审核。')
        version.status = 'review'
    elif payload.action == 'publish':
        if version.status != 'review' or not count:
            raise HTTPException(409, '请先提交审核并确认有有效正文。')
        if version.valid_until and version.valid_until.replace(tzinfo=version.valid_until.tzinfo or UTC) <= datetime.now(UTC):
            raise HTTPException(409, '资料有效期已结束，请修订后重新审核。')
        for old in session.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == document_id,
                                                               KnowledgeVersion.status == 'published')):
            old.status = 'superseded'
        session.flush()
        version.status, version.reviewer, version.reviewed_at = 'published', identity.username, datetime.now(UTC)
    else:
        if version.status != 'published':
            raise HTTPException(409, '仅当前发布版本可停用。')
        version.status = 'withdrawn'
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, '发布版本已变化，请刷新后重新核对。') from None
    return document_payload(session, document, detail=True)


@router.post('/search')
def search(payload: Search, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    result = retrieve(session, identity.username, payload.query, community_id=payload.community_id,
                      scenario=payload.scenario, semantic=payload.semantic)
    session.commit()
    return result


@router.get('/retrievals/{retrieval_id}')
def evidence(retrieval_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    record = session.get(KnowledgeRetrieval, retrieval_id)
    if not record or record.owner != identity.username:
        raise HTTPException(404, '未找到该检索证据。')
    return {'id': record.id, 'method': record.method, 'hits': record.hits, 'created_at': record.created_at}


@router.post('/documents/{document_id}/index')
def index(document_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    document = require_document(session, document_id, identity.username)
    if document.builtin and 'system_admin' not in identity.role_codes:
        raise HTTPException(403, '内置资料的语义索引由管理员维护。')
    from app.services.knowledge_vectors import configured, embed, index_identity
    if not configured():
        raise HTTPException(409, '请先配置独立的 Embedding 服务；聊天模型不等同于向量模型。')
    version = session.scalar(select(KnowledgeVersion).where(KnowledgeVersion.document_id == document_id,
                                                          KnowledgeVersion.status == 'published'))
    if not version:
        raise HTTPException(409, '请先发布有效资料。')
    if version.valid_until and version.valid_until.replace(tzinfo=version.valid_until.tzinfo or UTC) <= datetime.now(UTC):
        raise HTTPException(409, '资料已过期，请修订有效期后重建索引。')
    chunk_data = [(c.id, c.content) for c in session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id)
                                                           .order_by(KnowledgeChunk.ordinal))]
    version_id = version.id
    session.rollback()  # Remote computation does not hold a document transaction.
    try:
        vectors = []
        deadline = time.monotonic() + 45
        for offset in range(0, len(chunk_data), 16):
            if time.monotonic() > deadline:
                raise TimeoutError()
            vectors.extend(embed([text for _, text in chunk_data[offset:offset + 16]]))
    except Exception:
        raise HTTPException(502, 'Embedding 索引未完成；旧索引保持可用，请检查服务后重试。') from None
    version = session.get(KnowledgeVersion, version_id)
    if not version or version.status != 'published':
        raise HTTPException(409, '资料版本已经变化，请重新索引。')
    for (chunk_id, _), vector in zip(chunk_data, vectors):
        session.get(KnowledgeChunk, chunk_id).vector = vector
    version.embedding_model = index_identity()
    session.commit()
    return {'indexed_chunks': len(vectors), 'model': version.embedding_model}
