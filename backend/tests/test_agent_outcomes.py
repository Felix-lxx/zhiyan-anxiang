from types import SimpleNamespace

from sqlalchemy import select

from app.api.routes import operations
from app.models.agent import AgentDecisionCheck, AgentRun, AgentRunEvent
from app.models.operations import DrillSession
from app.services.agent_outcomes import interventions, population_metrics, settle_checks
from test_agent_workflow import proposal
from test_exercise_world import exercise


def test_observation_survives_stop_and_uses_original_horizon(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    data = start()
    ids = [p["id"] for p in data["simulation"]["residents"]][:2]
    plan = proposal(client, headers, root, ids)
    candidate = next(c for c in plan["candidates"] if c["can_apply"])
    url = root + "/agent/runs/" + plan["id"] + "/actions"
    body = {"action": "approve", "revision": 1, "candidate_id": candidate["id"]}
    approved = client.post(url, headers=headers, json=body)
    assert approved.status_code == 200, approved.text
    pending = approved.json()["outcomes"][0]
    assert pending["population"] == 2 and pending["result"] is None
    assert client.post(url, headers=headers, json=body).status_code == 200
    assert client.post(url, headers=headers, json={"action": "stop", "revision": 1}).status_code == 200
    due = candidate["forecast_at"] + 30
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, plan["id"])
        settle_checks(db, record, operations)
        assert len(list(db.scalars(select(AgentDecisionCheck)))) == 1
        assert db.scalar(select(AgentDecisionCheck)).status == "pending"
    tick(due + 12)  # Late scheduler must not compare 42 seconds to a 30-second forecast.
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, plan["id"])
        settle_checks(db, record, operations)
        check = db.scalar(select(AgentDecisionCheck))
        assert check.result["observed_at"] == due
        assert check.result["comparable"]
        assert record.status == "stopped"
        before = check.result.copy()
        settle_checks(db, record, operations)
        assert db.scalar(select(AgentDecisionCheck)).result == before
        assert len(list(db.scalars(select(AgentRunEvent).where(AgentRunEvent.kind == "outcome.checked")))) == 1
    replay = client.get(root + f"/replay?at_seconds={due}", headers=headers).json()
    expected, _ = population_metrics(replay["simulation"], ids)
    result = client.get(root + "/agent/runs", headers=headers).json()["runs"][0]["outcomes"][0]
    assert result["result"]["actual"] == expected


def test_ended_before_horizon_does_not_claim_full_forecast_delta(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    data = start()
    plan = proposal(client, headers, root, [data["simulation"]["residents"][0]["id"]])
    candidate = next(c for c in plan["candidates"] if c["can_apply"])
    response = client.post(root + "/agent/runs/" + plan["id"] + "/actions", headers=headers,
                           json={"action": "approve", "revision": 1, "candidate_id": candidate["id"]})
    assert response.status_code == 200, response.text
    with operations.SessionLocal() as db:
        drill = db.get(DrillSession, demo["drill_id"])
        drill.status = "ended"
        db.commit()
        settle_checks(db, db.get(AgentRun, plan["id"]), operations)
        result = db.scalar(select(AgentDecisionCheck)).result
        assert result["early_ended"] and not result["comparable"]
        assert result["delta"] is None and result["observed_at"] == clock["t"]


def test_interventions_exclude_own_commands_and_unrelated_people():
    def event(id, kind, payload, sequence):
        return SimpleNamespace(id=id, event_type=kind, payload=payload, sequence=sequence,
                               elapsed_seconds=10, message="记录 " + id)
    events = [
        event("own", "resident.command", {"resident_ids": ["a"]}, 2),
        event("receipt", "command.accepted", {"command_id": "cmd", "event_ids": ["own"]}, 3),
        event("other", "resident.command", {"resident_ids": ["b"]}, 4),
        event("manual", "resident.command", {"resident_ids": ["a"]}, 5),
        event("road", "road.reopened", {}, 6),
    ]
    changes, total = interventions(events, {"after_sequence": 1, "command_ids": ["cmd"], "resident_ids": ["a"]})
    assert total == 2 and [e["id"] for e in changes] == ["manual", "road"]
