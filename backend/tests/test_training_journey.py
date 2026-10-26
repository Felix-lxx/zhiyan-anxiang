"""Guidance must describe the authoritative result, not complete work for users."""
from copy import deepcopy
from types import SimpleNamespace

from app.services.training_journey import build_briefing, project_journey
from test_exercise_world import exercise
from test_kitchen_fire import kitchen


def event(kind, **payload):
    return SimpleNamespace(event_type=kind, payload=payload)


def state(**overrides):
    people = [dict(id="r1", label="居民 01", vulnerable=True, status="waiting", counted=False,
                   assisted=False, indoor_stage="room", route_reachable=True, release_at=10**9)]
    world = dict(residents=deepcopy(people), parameters={"fire_source_type": "kitchen"},
                 fire_source={"name": "1 号楼 · 2层东侧厨房"}, tasks=[], response_staff=[])
    values = dict(world=world, status="running", elapsed=20,
                  simulation={"residents": people, "environment": {}, "helpers": []},
                  tasks=[], robot=None, commands=[],
                  events=[event("robot.alarm_confirmed"), event("participant.acknowledge")])
    values.update(overrides)
    return values


def test_arrival_is_not_rollcall_and_cannot_complete():
    values = state()
    values["simulation"]["residents"][0].update(status="evacuated", assisted=True)
    result = project_journey(**values)
    assert result["phase"] == "verify"
    assert result["actions"][0]["kind"] == "rollcall"
    assert not result["completion"]["ready"]
    values["simulation"]["residents"][0]["counted"] = True
    assert project_journey(**values)["completion"]["ready"]
    values["commands"] = [{"status": "executing"}]
    assert not project_journey(**values)["completion"]["ready"]


def test_priority_actions_and_active_escort_are_not_duplicated():
    values = state(tasks=[dict(id="t1", title="燃气处置", status="verifying", can_submit=True, remaining_seconds=15)])
    values["simulation"]["residents"][0].update(route_reachable=False, release_at=10)
    values["simulation"]["helpers"] = [dict(resident_id="r1", state="approaching")]
    result = project_journey(**values)
    assert [a["kind"] for a in result["actions"]] == ["locate", "task"]
    assert result["actions"][1]["target_id"] == "t1"
    assert values["tasks"][0]["status"] == "verifying"


def test_paused_and_ended_do_not_claim_movement_or_completion():
    values = state(status="paused", robot={"task_queue": [dict(id="move", label="入口广播", status="executing", ends_at_seconds=35)]})
    paused = project_journey(**values)
    assert paused["paused"] and paused["waiting"][0]["detail"] == "约 15 秒后到达"
    values["status"] = "ended"
    ended = project_journey(**values)
    assert ended["phase"] == "review" and not ended["waiting"]
    assert [a["kind"] for a in ended["actions"]] == ["review"]
    assert ended["completion"]["blockers"] and not ended["completion"]["ready"]


def test_frozen_briefing_is_not_rewritten_by_live_projection():
    values = state()
    values["world"]["training_briefing"] = build_briefing(values["world"])
    frozen = deepcopy(values["world"])
    values["simulation"]["residents"][0]["counted"] = True
    result = project_journey(**values)
    assert result["briefing_origin"] == "frozen"
    result["briefing"]["objective"] = "client mutation"
    assert values["world"] == frozen
    assert frozen["training_briefing"]["fire_location"] == "1 号楼 · 2层东侧厨房"


def test_journey_requires_authorization_and_is_consistent_with_snapshot(kitchen):
    client, headers, _, _, created, root, tick = kitchen
    assert client.get(root + "/journey").status_code == 401
    initial = tick(0)
    journey = client.get(root + "/journey", headers=headers).json()
    assert journey == initial["journey"]
    assert journey["phase"] == "prepare" and journey["briefing_origin"] == "frozen"
    assert journey["briefing"]["population"] == 8
    assert journey["briefing"] == initial["simulation"]["world"]["training_briefing"]
    assert len(journey["briefing"]["responsibilities"]) == 4
    assert client.patch(root + "/state", headers=headers, json={"action": "start"}).is_success
    live = tick(35)
    assert live["journey"]["phase"] != "prepare"
    assert live["journey"]["briefing"] == journey["briefing"]
    assert len(live["journey"]["actions"]) <= 3
    reread = client.get(root, headers=headers).json()
    assert reread["journey"] == live["journey"]
    assert reread["latest_event_sequence"] == live["latest_event_sequence"]


def test_ready_run_is_resumable_without_creating_a_duplicate(exercise):
    client, headers, demo, root, *_ = exercise
    url = f"/api/v1/communities/{demo['community']['id']}/drill-history"
    first = client.get(url, headers=headers).json()
    assert first["latest_unfinished"]["id"] == demo["drill_id"]
    assert first["latest_unfinished"]["status"] == "ready"
    assert first["latest_review"] is None
    assert client.get(root + "/journey", headers=headers).is_success
    assert client.get(url, headers=headers).json()["total"] == first["total"]
