from fastapi.testclient import TestClient


def login_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Zhiyan@2026"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_main_case_runs_from_scene_to_score(client: TestClient, monkeypatch) -> None:
    clock = {"seconds": 0}
    monkeypatch.setattr("app.api.routes.operations.effective_elapsed", lambda drill: 0 if drill.status == "ready" else clock["seconds"])
    headers = login_headers(client)
    community = client.post("/api/v1/communities/demo", headers=headers).json()
    templates = client.get("/api/v1/scene-templates", headers=headers).json()
    main_template = next(item for item in templates if item["code"] == "night_charging_shed_fire")
    scene = client.post(
        f"/api/v1/communities/{community['id']}/scenes",
        headers=headers,
        json={"template_id": main_template["id"], "name": "主案例闭环测试"},
    ).json()
    objects = client.get(f"/api/v1/communities/{community['id']}/map-objects", headers=headers).json()
    charging_shed = next(item for item in objects if item["object_type"] == "charging_shed")
    parameters = client.patch(
        f"/api/v1/scenes/{scene['id']}/charging-shed-parameters",
        headers=headers,
        json={
            "fire_source_object_id": charging_shed["id"], "start_time": "20:15", "wind_direction": "微风",
            "resident_count": 60, "hydrant_status": "faulty", "south_lane_status": "restricted",
        },
    )
    assert parameters.status_code == 200
    assert client.post(f"/api/v1/scenes/{scene['id']}/validate", headers=headers).json()["passed"] is True
    assert client.post(f"/api/v1/scenes/{scene['id']}/publish", headers=headers).status_code == 200

    decision = client.post(
        f"/api/v1/scenes/{scene['id']}/decision-points",
        headers=headers,
        json={
            "name": "是否启动社区响应", "trigger_condition": "确认火情后", "responsible_role": "应急指挥人员",
            "time_limit_seconds": 30,
            "options": [
                {"label": "立即启动", "consequence": "派发物业断电与疏散任务"},
                {"label": "继续观察", "consequence": "响应延迟并增加风险"},
            ],
        },
    ).json()
    task_response = client.post(f"/api/v1/decision-options/{decision['options'][0]['id']}/execute", headers=headers)
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]

    drill_response = client.post(
        f"/api/v1/scenes/{scene['id']}/drills",
        headers=headers,
        json={"name": "闭环演练 01", "time_scale": 2},
    )
    assert drill_response.status_code == 201
    drill = drill_response.json()
    assert len(drill["participants"]) == 4
    drill_id = drill["id"]
    # Regression fixture: pre-v2 creation events had no frozen world. Keep this
    # historical replay/API contract covered alongside test_exercise_world.py.
    from app.api.routes.operations import SessionLocal
    from app.models.operations import DrillEvent
    from sqlalchemy import select
    with SessionLocal() as db:
        created = db.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == drill_id, DrillEvent.event_type == "drill.created"))
        created.payload = {}
        db.commit()
    assert client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "step"}).status_code == 409
    assert client.patch(f"/api/v1/drills/{drill_id}/state", headers=headers, json={"action": "start"}).json()["status"] == "running"
    moved = client.post(
        f"/api/v1/drills/{drill_id}/robot",
        headers=headers,
        json={"command": "move", "x": 72, "y": 36, "target": "3 号楼东侧入口"},
    ).json()
    target_event = next(event for event in moved["events"] if event["event_type"] == "robot.target_assigned")
    assert target_event["payload"]["target"] == "3 号楼东侧入口"
    assert len(target_event["payload"]["route_points"]) >= 2
    assert (target_event["payload"]["target_x"], target_event["payload"]["target_y"]) == (72, 36)
    assert target_event["payload"]["route_edge_ids"]
    assert (moved["robot"]["x"], moved["robot"]["y"]) != (72, 36)
    queued = client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "move", "x": 12, "y": 12, "target": "北门集合点"}).json()
    assert [item["status"] for item in queued["robot"]["task_queue"]] == ["executing", "queued"]
    assert queued["robot"]["task_queue"][1]["progress"] == 0
    cancelled = client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "cancel", "task_id": queued["robot"]["task_queue"][1]["id"]}).json()
    assert cancelled["robot"]["task_queue"][1]["status"] == "cancelled"
    assert client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "broadcast"}).status_code == 409
    invite = client.post(f"/api/v1/drills/{drill_id}/participant-invite", headers=headers).json()
    joined = client.get(f"/api/v1/participant/drills/{drill_id}?code={invite['code']}")
    assert joined.status_code == 200
    member = client.post(f"/api/v1/participant/drills/{drill_id}/join?code={invite['code']}", json={"role": "居民代表", "display_name": "手机参演者"}).json()
    public_feedback = client.post(
        f"/api/v1/participant/drills/{drill_id}/actions?code={invite['code']}",
        json={"role": "居民代表", "action": "acknowledge", "message": "手机端已收到告警", "participant_token": member["token"]},
    )
    assert public_feedback.status_code == 200
    resident_role = next(item for item in public_feedback.json()["participants"] if item["role"] == "居民代表")
    assert resident_role["action_count"] == 1
    assert resident_role["last_action"] == "acknowledge"
    ticket = client.post(f"/api/v1/participant/drills/{drill_id}/socket-ticket", json={"code":invite["code"]}).json()["ticket"]
    with client.websocket_connect(f"/api/v1/ws/drills/{drill_id}?ticket={ticket}&protocol=3") as websocket:
        synced = websocket.receive_json()
        assert synced["data"]["events"][0]["event_type"] == "participant.acknowledge"
    directed = client.post(
        f"/api/v1/drills/{drill_id}/residents",
        headers=headers,
        json={"resident_ids": ["resident-3", "resident-8"], "exit": "north", "action": "priority_assist"},
    ).json()
    assert next(item for item in directed["simulation"]["residents"] if item["id"] == "resident-3")["assisted"] is True
    participant = client.post(
        f"/api/v1/drills/{drill_id}/participant-actions",
        headers=headers,
        json={"role": "物业/网格员", "action": "arrived", "message": "已到达 3 号楼入口"},
    ).json()
    assert any(event["event_type"] == "participant.arrived" for event in participant["events"])
    completed = client.patch(f"/api/v1/drills/{drill_id}/tasks/{task_id}/complete", headers=headers).json()
    assert next(item for item in completed["tasks"] if item["id"] == task_id)["status"] == "completed"
    duplicate = client.patch(f"/api/v1/drills/{drill_id}/tasks/{task_id}/complete", headers=headers).json()
    assert len([event for event in duplicate["events"] if event["event_type"] == "task.completed"]) == 1
    for _ in range(82):
        history_snapshot = client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "step"}).json()
    assert next(item for item in history_snapshot["tasks"] if item["id"] == task_id)["status"] == "completed"
    assert next(item for item in history_snapshot["simulation"]["residents"] if item["id"] == "resident-3")["assisted"] is True
    invalid_drop = client.post(f"/api/v1/drills/{drill_id}/inject", headers=headers, json={"event_type": "hydrant_failure", "x": 20, "y": 20, "target": "1 号楼"})
    assert invalid_drop.status_code == 422
    south_edge = next(edge for edge in history_snapshot["simulation"]["road_network"]["edges"] if "南门" in edge["name"])
    injected = client.post(f"/api/v1/drills/{drill_id}/inject", headers=headers, json={"event_type": "channel_blocked", "road_edge_id": south_edge["id"], "x": (south_edge["start"]["x"] + south_edge["end"]["x"]) / 2, "y": (south_edge["start"]["y"] + south_edge["end"]["y"]) / 2, "target": "南门出口"}).json()
    assert injected["robot"]["state"] == "executing"
    assert injected["simulation"]["environment"]["south_lane"] == "blocked"
    assert len(injected["simulation"]["residents"]) == 18
    assert next(event for event in injected["events"] if event["event_type"] == "inject.channel_blocked")["payload"]["target"] == "南门出口"
    assert next(event for event in injected["events"] if event["event_type"] == "inject.channel_blocked")["payload"]["blocked_edge_id"]
    route_event = next(event for event in injected["events"] if event["event_type"] == "robot.replanned")
    assert south_edge["id"] not in route_event["payload"]["route_edge_ids"]
    assert (route_event["payload"]["target_x"], route_event["payload"]["target_y"]) == (72, 36)
    directed_event = client.post(f"/api/v1/drills/{drill_id}/director/advance", headers=headers).json()
    assert any(event["event_type"] == "director.cue" for event in directed_event["events"])
    assert client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "broadcast"}).status_code == 409
    clock["seconds"] = max(item["ends_at_seconds"] for item in directed_event["robot"]["task_queue"])
    arrived = client.get(f"/api/v1/drills/{drill_id}", headers=headers).json()
    assert arrived["robot"]["state"] == "arrived"
    assert (arrived["robot"]["x"], arrived["robot"]["y"]) == (72, 36)
    broadcast = client.post(f"/api/v1/drills/{drill_id}/robot", headers=headers, json={"command": "broadcast"}).json()
    assert broadcast["robot"]["state"] == "completed"
    ended = client.patch(f"/api/v1/drills/{drill_id}/state", headers=headers, json={"action": "end"}).json()
    assert ended["status"] == "ended"
    assert ended["score"]["total_score"] == sum(item["score"] for item in ended["score"]["details"])
    assert 80 <= ended["score"]["total_score"] <= 100
    assert any(event["event_type"] == "robot.replanned" for event in ended["events"])
    comparison = client.get(f"/api/v1/scenes/{scene['id']}/comparison", headers=headers).json()
    assert comparison[0]["score"] == ended["score"]["total_score"]
    report = client.get(f"/api/v1/drills/{drill_id}/report", headers=headers)
    assert report.status_code == 200
    assert report.json()["score"]["total_score"] == ended["score"]["total_score"]
    evidence = report.json()["evidence"]
    assert len({event["sequence"] for event in evidence}) == len(evidence)
    assert report.json()["simulation_summary"] == ended["simulation"]["summary"]
    replay = client.get(f"/api/v1/drills/{drill_id}/replay?at_seconds=0", headers=headers)
    assert replay.status_code == 200
    assert replay.json()["simulation"]["summary"]["total"] == 18
    branches = client.post(
        f"/api/v1/drills/{drill_id}/branches/compare",
        headers=headers,
        json={"baseline_strategy": "south_standard", "alternative_strategy": "north_priority"},
    )
    assert branches.status_code == 200
    assert branches.json()["source_state"]["road_graph_edges"] > 0
    assert branches.json()["projection_seconds"] == 90
    assert branches.json()["improvement"]["score"] == branches.json()["alternative"]["projected_score"] - branches.json()["baseline"]["projected_score"]
    assert branches.json()["worlds"]["baseline"]["parallel_strategy"] == "south_standard"
    assert branches.json()["worlds"]["alternative"]["parallel_strategy"] == "north_priority"
    assert branches.json()["worlds"]["alternative"]["residents"] != branches.json()["worlds"]["baseline"]["residents"]
    second_drill = client.post(
        f"/api/v1/scenes/{scene['id']}/drills",
        headers=headers,
        json={"name": "闭环演练 02", "time_scale": 1},
    ).json()
    assert next(item for item in second_drill["tasks"] if item["id"] == task_id)["status"] == "waiting"
    assert client.patch(f"/api/v1/drills/{second_drill['id']}/state", headers=headers, json={"action": "start"}).status_code == 200
    clock["seconds"] += 20
    second_ended = client.patch(f"/api/v1/drills/{second_drill['id']}/state", headers=headers, json={"action": "end"}).json()
    detailed_comparison = client.get(
        f"/api/v1/scenes/{scene['id']}/outcome-comparison",
        headers=headers,
        params={"baseline_id": drill_id, "candidate_id": second_drill["id"]},
    )
    assert detailed_comparison.status_code == 200
    comparison_data = detailed_comparison.json()
    assert len(comparison_data["runs"]) == 2
    assert comparison_data["comparison"]["baseline"]["id"] == drill_id
    assert comparison_data["comparison"]["candidate"]["id"] == second_drill["id"]
    assert comparison_data["comparison"]["delta"]["score"] == second_ended["score"]["total_score"] - ended["score"]["total_score"]
    assert comparison_data["comparison"]["baseline"]["evidence_count"] > 0
    invalid_comparison = client.get(
        f"/api/v1/scenes/{scene['id']}/outcome-comparison",
        headers=headers,
        params={"baseline_id": drill_id, "candidate_id": drill_id},
    )
    assert invalid_comparison.status_code == 422
    # Scheduler owns advancement; a connected observer must not tick the engine.
    import app.api.routes.operations as operations_route
    heartbeat_calls: list[str] = []
    original_advance = operations_route.advance_engine
    monkeypatch.setattr(operations_route, "advance_engine", lambda session, active_drill: heartbeat_calls.append(active_drill.id))
    ticket = client.post(f"/api/v1/drills/{second_drill['id']}/socket-ticket", headers=headers).json()["ticket"]
    with client.websocket_connect(f"/api/v1/ws/drills/{second_drill['id']}?ticket={ticket}&protocol=3") as websocket:
        assert websocket.receive_json()["type"] == "drill.snapshot"
    assert heartbeat_calls == []
    monkeypatch.setattr(operations_route, "advance_engine", original_advance)
    reset = client.post(f"/api/v1/communities/{community['id']}/demo-reset", headers=headers)
    assert reset.status_code == 200
    assert reset.json()["removed_drills"] == 2
    assert client.get(f"/api/v1/drills/{drill_id}", headers=headers).status_code == 404
    preserved_scenes = client.get(f"/api/v1/communities/{community['id']}/scenes", headers=headers).json()
    assert any(item["id"] == scene["id"] and item["status"] == "published" for item in preserved_scenes)


def test_drill_state_machine_rejects_invalid_transition(client: TestClient) -> None:
    headers = login_headers(client)
    missing = client.patch("/api/v1/drills/missing/state", headers=headers, json={"action": "start"})
    assert missing.status_code == 404
