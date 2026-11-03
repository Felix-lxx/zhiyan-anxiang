"""Knowledge lifecycle, access-controlled retrieval and immutable citation snapshots."""
from collections import Counter
from datetime import UTC, datetime
import json
import math
from pathlib import Path
import re

from fastapi import HTTPException
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import Community
from app.models.knowledge import KnowledgeDocument, KnowledgeVersion, KnowledgeChunk, KnowledgeRetrieval, KnowledgeExperience
from app.services.knowledge_ingestion import chunks, digest


def require_community(session: Session, community_id: str | None, owner: str):
    if community_id:
        community = session.get(Community, community_id)
        if not community or community.owner.username != owner:
            raise HTTPException(404, '未找到该社区。')


def allowed(document: KnowledgeDocument, owner: str) -> bool:
    return document.builtin or document.owner == owner


def require_document(session: Session, document_id: str, owner: str, write=False):
    document = session.get(KnowledgeDocument, document_id)
    if not document or not allowed(document, owner):
        raise HTTPException(404, '未找到该知识资料。')
    if write and (document.builtin or document.owner != owner):
        raise HTTPException(403, '内置资料只读，请复制为自己的资料后修改。')
    return document


def add_version(session, document, pages, filename='', extraction='text', failure='', valid_until=None):
    previous = session.scalar(select(KnowledgeVersion).where(KnowledgeVersion.document_id == document.id)
                              .order_by(KnowledgeVersion.number.desc()))
    version = KnowledgeVersion(document_id=document.id, number=(previous.number + 1 if previous else 1),
        status='failed' if failure else 'draft', filename=filename, extraction=extraction,
        pages=pages,
        valid_until=valid_until,
        content_hash=digest('\n'.join(text for _, text in pages)), failure=failure)
    session.add(version)
    session.flush()
    for ordinal, (anchor, text) in enumerate(chunks(pages), 1):
        session.add(KnowledgeChunk(version_id=version.id, ordinal=ordinal, anchor=anchor,
                                   content=text, content_hash=digest(text)))
    session.flush()
    return version


def seed_knowledge(session: Session):
    catalog = json.loads((Path(__file__).parents[1] / 'data' / 'fire_knowledge.json').read_text(encoding='utf-8'))
    for item in catalog:
        if session.get(KnowledgeDocument, item['id']):
            continue
        try:
            with session.begin_nested():
                document = KnowledgeDocument(id=item['id'], title=item['title'], category=item['category'],
                    scenario=item['scenario'], source_url=item['source_url'], publisher=item['publisher'], builtin=True)
                session.add(document)
                session.flush()
                version = add_version(session, document, [('编写摘要／训练说明', item['content'])], extraction='curated_summary')
                version.status = 'published'
                version.reviewer = '项目内置资料整理'
                version.reviewed_at = datetime(2026, 11, 2, tzinfo=UTC)
        except IntegrityError:
            # Another worker already seeded this exact immutable document ID.
            continue
    session.commit()


def document_payload(session, document, detail=False):
    versions = list(session.scalars(select(KnowledgeVersion).where(KnowledgeVersion.document_id == document.id)
                                    .order_by(KnowledgeVersion.number.desc())))
    value = {'id': document.id, 'title': document.title, 'category': document.category,
             'scenario': document.scenario, 'source_url': document.source_url, 'publisher': document.publisher,
             'community_id': document.community_id, 'builtin': document.builtin, 'versions': []}
    source = session.scalar(select(KnowledgeExperience).where(KnowledgeExperience.document_id == document.id)) if detail and document.category == 'experience' else None
    if source:
        value['experience'] = {**source.basis, 'basis_hash': source.basis_hash}
    for version in versions:
        data = {key: getattr(version, key) for key in ('id', 'number', 'status', 'filename', 'extraction',
            'failure', 'reviewer', 'reviewed_at', 'embedding_model', 'content_hash', 'created_at', 'valid_until')}
        expiry = version.valid_until
        expired = expiry is not None and expiry.replace(tzinfo=expiry.tzinfo or UTC) <= datetime.now(UTC)
        data['effective_status'] = 'expired' if version.status == 'published' and expired else version.status
        if detail:
            data['text'] = '\n\n'.join(text for _, text in version.pages)
            data['chunks'] = [{'id': c.id, 'anchor': c.anchor, 'content': c.content, 'content_hash': c.content_hash}
                for c in session.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id)
                                         .order_by(KnowledgeChunk.ordinal))]
        value['versions'].append(data)
    return value


def terms(text):
    text = text.lower()
    tokens = re.findall(r'[a-z0-9_]+', text)
    for phrase in re.findall(r'[\u4e00-\u9fff]+', text):
        tokens.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return Counter(tokens)


def expand_query(query):
    concepts = {'老人': '老年人 重点人员 护送', '残障': '行动不便 重点人员', '堵了': '堵塞 疏散通道 消防车道',
                '充电棚': '电动自行车 充电', '烟雾': '烟气 躲火避烟', '关门': '房门 防火门 控烟',
                '煤气': '燃气 阀门', '机器人': '广播 到位 任务', '没到': '集合清点 失联'}
    return query + ' ' + ' '.join(value for word, value in concepts.items() if word in query)


def retrieve(session: Session, owner: str, query: str, *, community_id=None, scenario='all',
             drill_id=None, semantic=False, limit=5, situation=None):
    require_community(session, community_id, owner)
    statement = select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument).join(
        KnowledgeVersion, KnowledgeChunk.version_id == KnowledgeVersion.id).join(
        KnowledgeDocument, KnowledgeVersion.document_id == KnowledgeDocument.id).where(
        KnowledgeVersion.status == 'published',
        or_(KnowledgeVersion.valid_until.is_(None), KnowledgeVersion.valid_until > datetime.now(UTC)),
        or_(KnowledgeDocument.builtin.is_(True), KnowledgeDocument.owner == owner),
        or_(KnowledgeDocument.community_id.is_(None), KnowledgeDocument.community_id == community_id))
    if scenario != 'all':
        statement = statement.where(KnowledgeDocument.scenario.in_(['all', scenario]))
    rows = list(session.execute(statement.order_by(KnowledgeDocument.id, KnowledgeChunk.ordinal).limit(2001)))
    if len(rows) > 2000:
        raise HTTPException(409, '当前检索范围超过本地容量，请缩小社区或案例范围。')
    vectors, method, notice = {}, 'keyword', '关键词检索；本次未调用语义向量服务。'
    if semantic:
        from app.services.knowledge_vectors import query_vectors
        vectors, method, notice = query_vectors(query, rows)
    query_terms = terms(expand_query(query))
    documents = [terms(document.title + ' ' + chunk.content) for chunk, _, document in rows]
    frequency = Counter(term for document in documents for term in document)
    average = sum(sum(d.values()) for d in documents) / max(1, len(documents))
    ranked = []
    for (chunk, version, document), words in zip(rows, documents):
        score = 0.
        for term in query_terms:
            tf = words.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(documents) - frequency[term] + .5) / (frequency[term] + .5))
            score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * sum(words.values()) / max(1, average)))
            if term in document.title:
                score += .6
        vector_score = vectors.get(chunk.id, 0)
        if score > 0 or vector_score > .5:
            ranked.append((score, vector_score, chunk, version, document))
    # Rank fusion keeps vector scale and keyword scale from being confused.
    keyword_rank = {item[2].id: i + 1 for i, item in enumerate(sorted(ranked, key=lambda x: -x[0])) if item[0] > 0}
    vector_rank = {item[2].id: i + 1 for i, item in enumerate(sorted(ranked, key=lambda x: -x[1])) if item[1] > .5}
    ranked.sort(key=lambda x: -(1 / (60 + keyword_rank[x[2].id]) if x[2].id in keyword_rank else 0)
                - (1 / (60 + vector_rank[x[2].id]) if x[2].id in vector_rank else 0))
    # One bounded query for all source records, rather than one lookup per hit.
    experience_ids = {document.id for _, _, document in rows if document.category == 'experience'}
    sources = {}
    ordered_ids = sorted(experience_ids)
    for offset in range(0, len(ordered_ids), 500):
        sources.update({source.document_id: source for source in session.scalars(select(KnowledgeExperience).where(
            KnowledgeExperience.document_id.in_(ordered_ids[offset:offset + 500])))})
    from app.services.knowledge_applicability import assess_experience, assessment
    hits, per_document = [], Counter()
    for score, vector_score, chunk, version, document in ranked:
        if per_document[document.id] >= 2:
            continue
        per_document[document.id] += 1
        hits.append({'id': f'K{len(hits) + 1}', 'document_id': document.id, 'version_id': version.id,
            'version': version.number, 'chunk_id': chunk.id, 'title': document.title, 'anchor': chunk.anchor,
            'content': chunk.content, 'content_hash': chunk.content_hash, 'source_url': document.source_url,
            'publisher': document.publisher, 'category': document.category, 'scenario': document.scenario})
        if document.category == 'experience':
            source = sources.get(document.id)
            if source:
                hits[-1]['experience'] = {key: source.basis.get(key) for key in ('drill_id', 'run_id', 'revision', 'observed_at',
                    'population', 'predicted', 'actual', 'scene_version_id', 'intervention_count', 'parameters',
                    'forecast_engine_revision', 'observed_engine_revision')}
                hits[-1]['experience']['basis_hash'] = source.basis_hash
            hits[-1]['applicability'] = assess_experience(source.basis if source else None, situation)
        if len(hits) >= limit:
            break
    record = KnowledgeRetrieval(owner=owner, community_id=community_id, drill_id=drill_id,
        query_hash=digest(query), method=method, notice=notice, hits=hits)
    session.add(record)
    session.flush()
    return {'retrieval_id': record.id, 'retrieved_at': record.created_at.isoformat(),
            'method': method, 'notice': notice, 'hits': hits, 'assessment': assessment(hits)}
