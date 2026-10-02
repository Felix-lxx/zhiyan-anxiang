from copy import deepcopy
import pytest

from app.services.realtime import snapshot_patch, SnapshotCache
from test_exercise_world import exercise


def apply_patch(data, changes):
    data = deepcopy(data)
    for change in changes:
        target = data
        for key in change["path"][:-1]:
            target = target[key]
        if change.get("remove"):
            del target[change["path"][-1]]
        else:
            target[change["path"][-1]] = change["value"]
    return data


def test_command_retry_is_idempotent_and_residents_really_arrive(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    start()
    payload = {"command_id": "evacuate-once-001", "kind": "residents.assign", "arguments": {"resident_ids": ["resident-1"], "exit": "north"}}
    first = client.post(root + '/commands', headers=headers, json=payload)
    assert first.status_code == 200, first.text
    state = first.json()
    receipt = state["commands"][0]
    assert receipt["id"] == payload["command_id"] and receipt["status"] == "executing"
    assert receipt["progress"] < 1 and receipt["event_ids"]
    retry = client.post(root + '/commands', headers=headers, json=payload).json()
    assert retry["latest_event_sequence"] == state["latest_event_sequence"]
    assert len([e for e in retry["events"] if e["event_type"] == "resident.command"]) == 1
    assert client.post(root + '/commands', headers=headers, json={**payload, "arguments": {"resident_ids": ["resident-1"], "exit": "south"}}).status_code == 409
    result = tick(500)
    assert result["commands"][0]["status"] == "completed"
    assert result["commands"][0]["completed_count"] == 1
    assert result["simulation"]["residents"][0]["status"] == "evacuated"


def test_invalid_command_rolls_back_receipt_and_effects(exercise):
    client, headers, _, root, _, _, _, tick, start = exercise
    start()
    before = tick(20)
    bad = {"command_id": "invalid-command-001", "kind": "residents.assign", "arguments": {"resident_ids": ["does-not-exist"], "exit": "north"}}
    assert client.post(root + '/commands', headers=headers, json=bad).status_code == 422
    after = tick(20)
    assert after["latest_event_sequence"] == before["latest_event_sequence"]
    assert after["commands"] == []
    malformed = {**bad, "arguments": {"exit": "invalid"}}
    assert client.post(root + '/commands', headers=headers, json=malformed).status_code == 422


def test_robot_receipt_tracks_real_queue_and_cancel(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    start()
    args = {"command": "move", "x": 58, "y": 54, "target": "楼门广播点"}
    state = client.post(root + '/commands', headers=headers, json={"command_id": "robot-live-001", "kind": "robot.command", "arguments": args}).json()
    receipt = state["commands"][0]
    assert receipt["status"] in {"executing", "queued"}
    task = next(t for t in state["robot"]["task_queue"] if t["id"] in receipt["event_ids"])
    assert receipt["remaining_seconds"] == task["ends_at_seconds"] - state["elapsed_seconds"]
    paused = client.patch(root + '/state', headers=headers, json={"action": "pause"}).json()
    assert paused["commands"][0]["status"] == "paused"
    client.patch(root + '/state', headers=headers, json={"action": "resume"})
    done = tick(task["ends_at_seconds"] + 1)
    assert done["commands"][0]["status"] == "completed"
    assert done["commands"][0]["progress"] == 1


def test_two_clients_receive_same_road_delta_and_reconnect_snapshot(exercise, monkeypatch):
    client, headers, demo, root, _, code, clock, tick, start = exercise
    start()
    tick(clock["t"])
    from app.api.routes import operations
    calls = []
    original = operations.snapshot
    monkeypatch.setattr(operations, "snapshot", lambda *a, **kw: (calls.append(1), original(*a, **kw))[1])
    url = f"/api/v1/ws/drills/{demo['drill_id']}?code={code}&protocol=2"
    with client.websocket_connect(url) as director, client.websocket_connect(url) as phone:
        base = director.receive_json()["data"]
        phone_base = phone.receive_json()["data"]
        assert base == phone_base
        assert len(calls) == 1  # Same state version is not replayed once per viewer.
        edge = next(e for e in base["simulation"]["road_network"]["edges"] if e["status"] != "blocked")
        response = client.post(root + '/commands', headers=headers, json={"command_id": "block-road-once-001", "kind": "event.inject", "arguments": {"event_type": "channel_blocked", "road_edge_id": edge["id"]}})
        assert response.status_code == 200, response.text
        messages = [director.receive_json(), phone.receive_json()]
        for message in messages:
            assert message["type"] == "drill.delta"
            rebuilt = apply_patch(base, message["patch"])
            assert rebuilt["state_version"] == response.json()["state_version"]
            assert next(e for e in rebuilt["simulation"]["road_network"]["edges"] if e["id"] == edge["id"])["status"] == "blocked"
            assert rebuilt["commands"][0]["status"] == "completed"
            assert rebuilt["score_preview"] == response.json()["score_preview"]
            assert all(p["path"][:2] != ["simulation", "world"] for p in message["patch"])
    with client.websocket_connect(url) as reconnected:
        assert reconnected.receive_json()["data"]["state_version"] == response.json()["state_version"]


def test_patch_handles_deletions_null_and_cache_eviction():
    before = {"state_version": "1:0", "simulation": {"fixed": {"name": "sample"}, "people": [{"id": "a"}], "removed": 1}, "nullable": 2}
    after = {"state_version": "2:0", "simulation": {"fixed": {"name": "sample"}, "people": [{"id": "b"}]}, "nullable": None}
    assert apply_patch(before, snapshot_patch(before, after)) == after
    cache = SnapshotCache(1)
    assert cache.get('a', '1:0', lambda: before) == before
    cache.get('b', '2:0', lambda: after)
    assert cache.get('a', '2:0', lambda: after) == after


def test_receipt_failure_rolls_back_already_flushed_domain_events(exercise, monkeypatch):
    from app.api.routes import operations
    client, headers, _, root, _, _, clock, tick, start = exercise
    start()
    before = tick(clock['t'])
    original = operations.append_event

    def fail_receipt(session, drill, event_type, *args, **kwargs):
        if event_type == 'command.accepted':
            raise RuntimeError('Injected receipt storage failure')
        return original(session, drill, event_type, *args, **kwargs)

    monkeypatch.setattr(operations, 'append_event', fail_receipt)
    with pytest.raises(RuntimeError, match='Injected receipt'):
        client.post(root + '/commands', headers=headers, json={
            'command_id': 'atomic-rollback-001', 'kind': 'residents.assign',
            'arguments': {'resident_ids': ['resident-1'], 'exit': 'north'},
        })
    after = tick(clock['t'])
    assert after['latest_event_sequence'] == before['latest_event_sequence']
    assert after['simulation'] == before['simulation']
    assert after['commands'] == []


def test_stale_version_does_not_apply_command(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    before = start()
    response = client.post(root + '/commands', headers=headers, json={
        'command_id': 'stale-version-001', 'kind': 'residents.assign',
        'expected_sequence': before['latest_event_sequence'] - 1,
        'arguments': {'resident_ids': ['resident-1'], 'exit': 'north'},
    })
    assert response.status_code == 409
    assert tick(clock['t'])['latest_event_sequence'] == before['latest_event_sequence']
