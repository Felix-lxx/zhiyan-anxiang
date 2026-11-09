"""Account-scoped chat storage with pagination, idempotency and clear generations."""
from copy import deepcopy
import json

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models.operations import DrillSession
from app.models.training import AssistantConversation, AssistantExchange
from app.services.command_lock import serialized_command
from app.services.knowledge_ingestion import digest


def conversation(session, drill_id, owner, *, create=False):
    row = session.scalar(select(AssistantConversation).where(
        AssistantConversation.drill_session_id == drill_id, AssistantConversation.owner == owner)
        .execution_options(populate_existing=True))
    if row is None and create:
        row = AssistantConversation(drill_session_id=drill_id, owner=owner, generation=0, next_sequence=1)
        session.add(row)
        session.flush()
    return row


def request_digest(payload):
    return digest(json.dumps(payload.model_dump(exclude={'request_id', 'conversation_generation'}),
                             sort_keys=True, ensure_ascii=False))


def prepare_request(session, drill_id, owner, payload):
    row = conversation(session, drill_id, owner)
    current = row.generation if row else 0
    if payload.conversation_generation is not None and payload.conversation_generation != current:
        raise HTTPException(409, '对话已在其他页面清空，请重新读取已保存对话后提问。')
    existing = session.scalar(select(AssistantExchange).where(
        AssistantExchange.conversation_id == row.id, AssistantExchange.generation == current,
        AssistantExchange.request_id == payload.request_id)) if row and payload.request_id else None
    if existing and existing.request_hash != request_digest(payload):
        raise HTTPException(409, '该请求编号已用于其他问题，请重新发起提问。')
    return current, deepcopy(existing.reply) if existing else None


def conversation_page(session, drill_id, owner, limit, before=None):
    row = conversation(session, drill_id, owner)
    if row is None:
        return {'generation': 0, 'items': [], 'next_before': None}
    statement = select(AssistantExchange).where(AssistantExchange.conversation_id == row.id,
        AssistantExchange.generation == row.generation)
    if before is not None:
        statement = statement.where(AssistantExchange.sequence < before)
    rows = list(session.scalars(statement.order_by(AssistantExchange.sequence.desc()).limit(limit + 1)))
    page = rows[:limit]
    return {'generation': row.generation,
        'next_before': page[-1].sequence if len(rows) > limit else None,
        'items': [{'sequence': item.sequence, 'question': item.question, 'reply': item.reply,
                   'created_at': item.created_at} for item in reversed(page)]}


@serialized_command
def save_exchange(session, drill_id, owner, payload, expected_generation, request_id, reply):
    # Lock only the short storage transaction, never a model/network request.
    session.execute(select(DrillSession.id).where(DrillSession.id == drill_id).with_for_update())
    row = conversation(session, drill_id, owner, create=True)
    if row.generation != expected_generation:
        raise HTTPException(409, '对话已清空，本次旧请求未重新写入。请重新读取对话。')
    existing = session.scalar(select(AssistantExchange).where(
        AssistantExchange.conversation_id == row.id, AssistantExchange.generation == row.generation,
        AssistantExchange.request_id == request_id))
    fingerprint = request_digest(payload)
    if existing:
        if existing.request_hash != fingerprint:
            raise HTTPException(409, '请求编号冲突，请重新提问。')
        return deepcopy(existing.reply)
    saved = {**reply, 'conversation_generation': row.generation, 'sequence': row.next_sequence}
    session.add(AssistantExchange(conversation_id=row.id, generation=row.generation,
        sequence=row.next_sequence, request_id=request_id, request_hash=fingerprint,
        question=payload.message, reply=saved))
    row.next_sequence += 1
    session.commit()
    return saved


@serialized_command
def clear_conversation(session, drill_id, owner, expected_generation):
    session.execute(select(DrillSession.id).where(DrillSession.id == drill_id).with_for_update())
    row = conversation(session, drill_id, owner, create=True)
    if row.generation != expected_generation:
        raise HTTPException(409, '对话版本已变化，请先重新读取。')
    session.execute(delete(AssistantExchange).where(AssistantExchange.conversation_id == row.id))
    row.generation += 1
    session.commit()
    return {'generation': row.generation, 'items': [], 'next_before': None}
