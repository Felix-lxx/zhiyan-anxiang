"""Once-only forecast checks against the authoritative historical simulation.

Reads never advance a workflow. The scheduler settles each observation at its
original horizon, even when the run has already completed or relinquished control.
"""
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.models.agent import AgentDecisionCheck, AgentRunEvent
from app.models.operations import DrillEvent, DrillSession


def register_check(session, run, candidate, approved_at):
    sequence = session.scalar(select(DrillEvent.sequence).where(
        DrillEvent.drill_session_id == run.drill_session_id
    ).order_by(DrillEvent.sequence.desc()).limit(1)) or 0
    session.add(AgentDecisionCheck(
        run_id=run.id, revision=run.revision, status="pending",
        due_seconds=candidate["forecast_at"] + candidate["forecast_seconds"],
        basis={
            "title": candidate["title"], "forecast_at": candidate["forecast_at"],
            "forecast_seconds": candidate["forecast_seconds"], "approved_at": approved_at,
            "after_sequence": candidate.get("forecast_sequence", sequence),
            "resident_ids": [p["id"] for p in candidate["assignments"]],
            "command_ids": [s["command_id"] for s in run.steps],
            "predicted": {key: candidate["metrics"][key] for key in ("arrived", "exposed", "queue_seconds")},
        },
    ))


def population_metrics(simulation, resident_ids):
    ids = set(resident_ids)
    people = [p for p in simulation["residents"] if p["id"] in ids]
    return {
        "arrived": sum(p["status"] == "evacuated" for p in people),
        "exposed": sum(p.get("smoke_exposure", 0) > 5 for p in people),
        "queue_seconds": round(sum(p.get("queue_seconds", 0) for p in people)),
    }, len(people)


def interventions(events, basis):
    """Bound the displayed list, preserving the full count and event references."""
    own_commands = set(basis["command_ids"])
    own_events = {eid for event in events if event.event_type == "command.accepted"
                  and event.payload.get("command_id") in own_commands
                  for eid in event.payload.get("event_ids", [])}
    ids = set(basis["resident_ids"])
    result = []
    for event in events:
        if event.sequence <= basis["after_sequence"] or event.id in own_events:
            continue
        kind = event.event_type
        relevant = kind.startswith(("inject.", "road.", "vehicle.", "task."))
        if kind == "resident.command":
            relevant = bool(ids.intersection(event.payload.get("resident_ids", [])))
        elif kind in {"robot.target_assigned", "robot.task_cancelled", "robot.broadcast_completed", "robot.replanned"}:
            relevant = True
        if relevant:
            result.append({"id": event.id, "sequence": event.sequence,
                           "at_seconds": event.elapsed_seconds, "kind": kind,
                           "message": getattr(event, "message", None) or kind})
    return result[:8], len(result)


def settle_checks(session, run, operations):
    # The row lock also fences simultaneous schedulers on PostgreSQL. SQLite's
    # existing serialized_command gate encloses the scheduler call.
    pending = list(session.scalars(select(AgentDecisionCheck).where(
        AgentDecisionCheck.run_id == run.id, AgentDecisionCheck.status == "pending"
    ).with_for_update()))
    if not pending:
        return
    drill = session.get(DrillSession, run.drill_session_id)
    if not drill:
        return
    elapsed = operations.effective_elapsed(drill)
    changed = False
    for check in pending:
        if elapsed < check.due_seconds and drill.status != "ended":
            continue
        claimed = session.execute(update(AgentDecisionCheck).where(
            AgentDecisionCheck.id == check.id, AgentDecisionCheck.status == "pending"
        ).values(status="checking"))
        if not claimed.rowcount:
            continue
        observed_at = min(elapsed, check.due_seconds)
        # Never include future actions in an earlier observation or event list.
        events = list(session.scalars(select(DrillEvent).where(
            DrillEvent.drill_session_id == drill.id,
            DrillEvent.elapsed_seconds <= observed_at
        ).order_by(DrillEvent.sequence)))
        actual, matched = population_metrics(
            operations.simulation_state(drill, events, observed_at, session=session),
            check.basis["resident_ids"],
        )
        changes, count = interventions(events, check.basis)
        delayed = max(0, check.basis["approved_at"] - check.basis["forecast_at"])
        early = observed_at < check.due_seconds
        complete_population = matched == len(check.basis["resident_ids"])
        comparable = not early and complete_population and delayed < check.basis["forecast_seconds"]
        check.status = "observed"
        check.result = {
            "observed_at": observed_at, "matched": matched, "early_ended": early,
            "approval_delay_seconds": delayed, "comparable": comparable,
            "actual": actual,
            "delta": {key: actual[key] - value for key, value in check.basis["predicted"].items()} if comparable else None,
            "interventions": changes, "intervention_count": count,
            "last_event_sequence": max((e.sequence for e in events), default=0),
            "notice": "场次提前结束，保留实际结果，不计算完整预测窗口差值。" if early else
                "目标居民数据不完整，无法进行同口径比较。" if not complete_population else
                "批准时预测窗口已结束，保留观察记录；请按当前现场重新预演。" if not comparable else
                "同一观察时刻、同一批居民的预测与实际差值；结合确认延迟和期间变化解读。",
        }
        session.add(AgentRunEvent(
            run_id=run.id, kind="outcome.checked", elapsed_seconds=observed_at,
            message=f"版本 {check.revision} 结果已核对：到场 {actual['arrived']} 人，暴露超阈值 {actual['exposed']} 人。",
        ))
        changed = True
    if changed:
        run.updated_at = datetime.now(UTC)
        session.commit()


def outcome_payload(session, run):
    rows = list(session.scalars(select(AgentDecisionCheck).where(
        AgentDecisionCheck.run_id == run.id
    ).order_by(AgentDecisionCheck.revision.desc()).limit(5)))
    return [{
        "revision": row.revision, "status": row.status, "due_seconds": row.due_seconds,
        "title": row.basis["title"], "forecast_at": row.basis["forecast_at"],
        "approved_at": row.basis["approved_at"], "population": len(row.basis["resident_ids"]),
        "predicted": row.basis["predicted"], "result": row.result,
    } for row in rows]
