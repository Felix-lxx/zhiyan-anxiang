"""Read-only execution projection. Receipts and spatial state are the evidence.

This module never submits commands or changes plan approval. Keep payloads bounded
even when a single step contains thousands of residents.
"""
from sqlalchemy import select

from app.models.operations import DrillCommand, DrillEvent


def execution_view(session, run, data):
    simulation = data["simulation"]
    people = {p["id"]: p for p in simulation["residents"]}
    helpers = {h["resident_id"]: h for h in simulation.get("helpers", [])}
    edges = {e["id"]: e for e in simulation.get("spatial_network", {}).get("edges", [])}
    command_ids = [s["command_id"] for s in run.steps]
    receipts = {c.command_id: c for c in session.scalars(select(DrillCommand).where(
        DrillCommand.drill_session_id == run.drill_session_id,
        DrillCommand.command_id.in_(command_ids)))} if command_ids else {}
    event_ids = {eid for c in receipts.values() for eid in c.event_ids}
    evidence = {e.id: e for e in session.scalars(select(DrillEvent).where(
        DrillEvent.drill_session_id == run.drill_session_id, DrillEvent.id.in_(event_ids)))} if event_ids else {}
    steps = []
    for original in run.steps:
        step = dict(original)
        step.pop("progress_signature", None)
        receipt = receipts.get(step["command_id"])
        if receipt:
            step.update(status=receipt.status, progress=receipt.progress, reason=receipt.reason)
        selected = [people[pid] for pid in step.get("resident_ids", []) if pid in people]
        attention = []
        for person in selected:
            helper = helpers.get(person["id"])
            edge = edges.get(person.get("waiting_for_edge") or person.get("current_edge_id"))
            arrived = person["status"] == "evacuated"
            blocked = not arrived and (person["status"] == "missing" or not person.get("route_reachable", True)
                                      or bool(helper and helper["state"] == "blocked"))
            attention.append({"id": person["id"], "label": person["label"],
                "location": person.get("last_location", "位置待更新"), "behavior": person.get("behavior", "等待现场更新"),
                "arrived": arrived, "blocked": blocked, "counted": bool(person.get("counted")),
                "queue_seconds": round(person.get("queue_seconds", 0)),
                "smoke_exposure": round(person.get("smoke_exposure", 0), 1),
                "bottleneck": edge.get("name", edge["id"]) if edge else None,
                "staff_name": helper.get("staff_name") if helper else None,
                "responsible": helper.get("responsible") if helper else None,
                "escort_state": helper["state"] if helper else None})
        attention.sort(key=lambda p: (not p["blocked"], p["arrived"], -p["smoke_exposure"], -p["queue_seconds"], p["id"]))
        linked = sorted((evidence[eid] for eid in (receipt.event_ids if receipt else []) if eid in evidence), key=lambda e: e.sequence)
        step["execution"] = {"total": len(selected), "arrived": sum(p["arrived"] for p in attention),
            "blocked": sum(p["blocked"] for p in attention),
            "queued": sum(not p["arrived"] and people[p["id"]].get("congestion", 0) > 0 for p in attention),
            "attention": attention[:6], "remaining_details": max(0, len(attention) - 6),
            "evidence": [{"id": e.id, "sequence": e.sequence, "at_seconds": e.elapsed_seconds,
                          "message": e.message} for e in linked[-4:]],
            "command_recorded": receipt is not None,
            "idle_seconds": max(0, data["elapsed_seconds"] - step.get("last_progress_at", data["elapsed_seconds"])),
            "stalled": run.status in {"executing", "waiting"} and data["status"] == "running" and step.get("status") == "executing" and
                       data["elapsed_seconds"] - step.get("last_progress_at", data["elapsed_seconds"]) >= 45}
        steps.append(step)
    staff = simulation.get("environment", {}).get("response_staff", [])
    return {"steps": steps, "at_seconds": data["elapsed_seconds"],
            "event_sequence": data["latest_event_sequence"],
            "staff": [{key: p.get(key) for key in ("id", "name", "state", "resident_id", "responsible", "completed_count")} for p in staff]}
