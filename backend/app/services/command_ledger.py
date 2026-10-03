"""Persist and expose command lifecycle without replacing the immutable event log."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations import DrillCommand, DrillSession


TERMINAL_STATUSES = {"completed", "cancelled", "superseded", "unfinished", "failed"}


def safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in arguments.items() if key not in {"participant_token", "token", "password"}}


def same_command(record: DrillCommand, kind: str, arguments: dict[str, Any], target_id: str | None) -> bool:
    return record.kind == kind and record.command_args == safe_arguments(arguments) and record.target_id == target_id


def apply_feedback(record: DrillCommand, feedback: dict[str, Any], elapsed: int) -> None:
    previous = record.status
    record.status = feedback["status"]
    record.label = feedback["label"]
    record.reason = feedback["reason"]
    record.progress = feedback["progress"]
    record.event_ids = feedback.get("event_ids", [])
    record.score_before = feedback.get("score_before")
    record.score_after_acceptance = feedback.get("score_after_acceptance")
    if record.accepted_at_seconds is None:
        record.accepted_at_seconds = feedback.get("accepted_at")
    if record.status in TERMINAL_STATUSES and previous not in TERMINAL_STATUSES:
        record.completed_at_seconds = elapsed
    record.updated_at = datetime.now(UTC)


def synchronize_records(session: Session, drill: DrillSession, feedback: list[dict[str, Any]], elapsed: int) -> None:
    by_id = {item["id"]: item for item in feedback}
    records = session.scalars(select(DrillCommand).where(DrillCommand.drill_session_id == drill.id)).all()
    for record in records:
        if record.status == "failed":
            continue
        item = by_id.get(record.command_id)
        if item:
            apply_feedback(record, item, elapsed)


def record_payload(record: DrillCommand, feedback: dict[str, Any] | None = None) -> dict[str, Any]:
    resident_ids = record.command_args.get("resident_ids", []) if record.kind == "residents.assign" else [record.command_args.get("resident_id")] if record.kind == "search.assign" else []
    resident_ids = [item for item in resident_ids if item]
    base = {
        "id": record.command_id,
        "kind": record.kind,
        "label": record.label,
        "actor": record.actor,
        "submitted_at": record.submitted_at_seconds,
        "accepted_at": record.accepted_at_seconds if record.accepted_at_seconds is not None else record.submitted_at_seconds,
        "completed_at": record.completed_at_seconds,
        "status": record.status,
        "progress": round(record.progress, 3),
        "reason": record.reason,
        "remaining_seconds": None,
        "resident_ids": resident_ids,
        "event_ids": record.event_ids,
        "score_before": record.score_before,
        "score_after_acceptance": record.score_after_acceptance,
        "completed_count": 0,
        "selected_count": len(resident_ids),
        "failure_code": record.failure_code,
    }
    return {**base, **(feedback or {})}


def ledger_feedback(session: Session, drill: DrillSession, derived: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer durable records while retaining receipts from older drill sessions."""
    records = list(session.scalars(
        select(DrillCommand)
        .where(DrillCommand.drill_session_id == drill.id)
        .order_by(DrillCommand.created_at.desc())
        .limit(24)
    ))
    derived_by_id = {item["id"]: item for item in derived}
    output = [record_payload(record, derived_by_id.get(record.command_id)) for record in records]
    recorded_ids = {record.command_id for record in records}
    output.extend(item for item in derived if item["id"] not in recorded_ids)
    return sorted(output, key=lambda item: (item.get("submitted_at", item.get("accepted_at", 0)), item.get("accepted_at", 0)), reverse=True)[:24]
