from app.api.routes import operations
from app.models.operations import DrillSession
from app.services.agent_realtime import AgentProjection
from test_exercise_world import exercise


def receive_type(socket, kind):
    for _ in range(8):
        message = socket.receive_json()
        if message["type"] == kind:
            return message
    raise AssertionError(f"Did not receive {kind}")


def test_plan_changes_stream_while_scene_clock_is_frozen_and_reconnects(exercise):
    client, headers, demo, root, *_ = exercise
    initial = client.get(root, headers=headers).json()
    def url():
        ticket = client.post(root + '/socket-ticket', headers=headers).json()["ticket"]
        return f"/api/v1/ws/drills/{demo['drill_id']}?ticket={ticket}&protocol=3&agent=1"
    with client.websocket_connect(url()) as socket:
        assert socket.receive_json()["type"] == "drill.snapshot"
        feed = receive_type(socket, "agent.snapshot")["data"]
        assert not feed["runs"]
        response = client.post(root + '/agent/runs', headers=headers, json={
            "request_id": "stream-goal-001", "goal": "将目标居民疏散", "resident_ids": ["resident-1"], "priority_assist": False})
        assert response.status_code == 201, response.text
        delta = receive_type(socket, "agent.delta")
        assert delta["base_version"] == feed["state_version"]
        assert delta["state_version"] != feed["state_version"]
        assert any(p["path"] == ["runs"] for p in delta["patch"])
        assert client.get(root, headers=headers).json()["state_version"] == initial["state_version"]
    with client.websocket_connect(url()) as reconnected:
        latest = receive_type(reconnected, "agent.snapshot")["data"]
        assert latest["runs"][0]["id"] == response.json()["id"]
        assert latest["source_version"] == initial["state_version"]


def test_private_projection_reuses_unchanged_state_and_scopes_actor(exercise):
    client, headers, demo, root, *_ = exercise
    response = client.post(root + '/agent/runs', headers=headers, json={
        "request_id": "private-goal-001", "goal": "将居民疏散", "resident_ids": ["resident-1"], "priority_assist": False})
    assert response.status_code == 201
    with operations.SessionLocal() as session:
        drill = session.get(DrillSession, demo["drill_id"])
        data = operations.snapshot(session, drill)
        projection = AgentProjection()
        first = projection.read(session, drill, "admin", data)
        assert projection.read(session, drill, "admin", data) is first
        assert first["runs"][0]["updated_at_us"] > 0
        assert projection.read(session, drill, "another-director", data)["runs"] == []


def test_participant_socket_cannot_subscribe_to_private_plan(exercise):
    client, _, demo, _, public, code, *_ = exercise
    ticket = client.post(public + '/socket-ticket', json={"code": code}).json()["ticket"]
    url = f"/api/v1/ws/drills/{demo['drill_id']}?ticket={ticket}&protocol=3&agent=1"
    with client.websocket_connect(url) as socket:
        assert socket.receive_json()["type"] == "drill.snapshot"
        assert socket.receive_json()["type"] == "drill.heartbeat"
