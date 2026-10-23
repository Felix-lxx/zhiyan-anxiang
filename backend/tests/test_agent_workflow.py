from sqlalchemy import select
from app.api.routes import operations
from app.models.agent import AgentRun
from app.models.operations import DrillCommand
from app.models.operations import DrillEvent
from copy import deepcopy
from app.services.agent_workflow import advance_run, reconcile_rollcall
from app.services.agent_resources import completed_broadcast, robot_support
from types import SimpleNamespace
from test_exercise_world import exercise


def proposal(client, headers, root, ids, request="goal-request-0001"):
    response = client.post(root + '/agent/runs', headers=headers, json={"request_id": request, "goal": "将选中居民分流疏散并护送重点人员", "resident_ids": ids})
    assert response.status_code == 201, response.text
    return response.json()


def test_goal_preview_approve_resume_and_manual_takeover(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    data = start()
    ids = [p["id"] for p in data["simulation"]["residents"] if not p["vulnerable"]][:4]
    before = data["latest_event_sequence"]
    run = proposal(client, headers, root, ids)
    assert run["status"] == "awaiting_approval" and 1 <= len(run["candidates"]) <= 2
    assert len({tuple((p['id'], p['exit']) for p in c['assignments']) for c in run['candidates']}) == len(run['candidates'])
    assert client.get(root, headers=headers).json()["latest_event_sequence"] == before
    assert proposal(client, headers, root, ids)["id"] == run["id"]
    selected = next(p for p in run["candidates"] if p["can_apply"])
    url = root + '/agent/runs/' + run["id"] + '/actions'
    payload = {"action": "approve", "revision": run["revision"], "candidate_id": selected["id"]}
    begun = client.post(url, headers=headers, json=payload)
    assert begun.status_code == 200, begun.text
    assert all(s["command_id"].startswith('agent-') for s in begun.json()["steps"])
    assert begun.json()["decision"]["allocation"] == selected["allocation"]
    assert begun.json()["decision"]["metrics"] == selected["metrics"]
    projected = begun.json()["steps"][0]["execution"]
    assert projected["command_recorded"] and projected["attention"] and projected["evidence"]
    assert projected["attention"][0]["id"] in ids
    assert begun.json()["execution"]["event_sequence"] >= before
    again = client.post(url, headers=headers, json=payload)
    assert again.status_code == 200, again.text
    with operations.SessionLocal() as db:
        initial_ids = list(db.scalars(select(DrillCommand.command_id)))
        assert len([entry for entry in db.get(AgentRun, run["id"]).evidence if entry.get("decision")]) == 1
        advance_run(db, db.get(AgentRun, run["id"]), SimpleNamespace(username="admin"))
        assert list(db.scalars(select(DrillCommand.command_id))) == initial_ids
    # Direct legacy commands must also relinquish automatic control.
    manual = client.post(root + '/residents', headers=headers, json={"resident_ids": ids[:1], "exit": "south", "action": "evacuate"})
    assert manual.status_code == 200, manual.text
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run["id"])
        advance_run(db, record, SimpleNamespace(username="admin"))
        assert record.status == "taken_over"


def test_goal_escort_capacity_completion_and_rollcall(exercise):
    client, headers, demo, root, public, code, clock, tick, start = exercise
    with operations.SessionLocal() as db:
        created = db.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == demo["drill_id"], DrillEvent.event_type == "drill.created"))
        payload = deepcopy(created.payload)
        for person in payload["world"]["residents"][:6]: person["vulnerable"] = True
        created.payload = payload; db.commit()
    data = start()
    for edge in data["simulation"]["road_network"]["edges"]:
        if edge["status"] != "open" and not edge.get("geometry_blocked"): assert client.post(root + '/roads/' + edge["id"] + '/reopen', headers=headers).status_code == 200
    ids = [p["id"] for p in data["simulation"]["residents"] if p["vulnerable"]][:5]
    run = proposal(client, headers, root, ids)
    selected = next(p for p in run["candidates"] if p["can_apply"])
    begun = client.post(root + '/agent/runs/' + run["id"] + '/actions', headers=headers, json={"action": "approve", "revision": 1, "candidate_id": selected["id"]})
    assert begun.status_code == 200, begun.text
    assert any(s["status"] == "waiting" for s in begun.json()["steps"])
    for _ in range(12):
        data = tick(clock["t"] + 90)
        assert sum(h["state"] != "completed" for h in data["simulation"]["helpers"]) <= 4
        with operations.SessionLocal() as db:
            record = db.get(AgentRun, run["id"])
            advance_run(db, record, SimpleNamespace(username="admin"))
            if record.status == "awaiting_rollcall": break
    else: raise AssertionError("Escort waves did not finish")
    member = client.post(public + '/join?code=' + code, json={"role": "居民代表", "display_name": "清点员"}).json()
    checked = client.post(public + '/actions?code=' + code, json={"role": "居民代表", "action": "resident_counted", "message": "逐人核验已到集合点", "participant_token": member["token"], "resident_ids": ids})
    assert checked.status_code == 200, checked.text
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run["id"])
        reconcile_rollcall(db, record, SimpleNamespace(username="admin"))
        assert record.status == "completed"


def test_stale_plan_and_stop_do_not_move_residents(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    data = start()
    ids = [data["simulation"]["residents"][0]["id"]]
    run = proposal(client, headers, root, ids)
    clock["t"] += 46
    visible = client.get(root + '/agent/runs', headers=headers).json()["runs"][0]
    assert not visible["approval_guard"]["can_approve"]
    assert visible["approval_guard"]["needs_replan"]
    assert visible["execution"]["coordination"]["next_action"]["kind"] == "replan"
    url = root + '/agent/runs/' + run["id"] + '/actions'
    stale = client.post(url, headers=headers, json={"action": "approve", "revision": 1, "candidate_id": run["candidates"][0]["id"]})
    assert stale.status_code == 409
    refreshed = client.post(url, headers=headers, json={"action": "replan", "revision": 1})
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["revision"] == 2
    stopped = client.post(url, headers=headers, json={"action": "stop", "revision": 2})
    assert stopped.status_code == 200 and stopped.json()["status"] == "stopped"
    with operations.SessionLocal() as db:
        assert not list(db.scalars(select(DrillCommand)))


def robot_proposal(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    for edge in data["simulation"]["road_network"]["edges"]:
        if edge["status"] != "open" and not edge.get("geometry_blocked"):
            assert client.post(root + '/roads/' + edge["id"] + '/reopen', headers=headers).status_code == 200
    resident = next(p for p in data["simulation"]["residents"] if not p["vulnerable"])
    response = client.post(root + '/agent/runs', headers=headers, json={
        "request_id": "robot-joint-plan-0001", "goal": "将本楼居民分流疏散，并安排楼门广播",
        "resident_ids": [resident["id"]], "robot_broadcast": True, "priority_assist": False})
    assert response.status_code == 201, response.text
    run = response.json()
    candidate = next(c for c in run["candidates"] if c["can_apply"])
    return run, candidate


def test_robot_arrival_broadcast_runs_parallel_and_resumes_once(exercise):
    client, headers, demo, root, _, _, clock, tick, _ = exercise
    run, candidate = robot_proposal(exercise)
    assert candidate["robot_support"]["duration_seconds"] >= 8
    with operations.SessionLocal() as db:
        assert not list(db.scalars(select(DrillCommand)))
    response = client.post(root + '/agent/runs/' + run["id"] + '/actions', headers=headers, json={
        "action": "approve", "revision": 1, "candidate_id": candidate["id"]})
    assert response.status_code == 200, response.text
    begun = response.json()
    assert any(s["resident_ids"] and s["status"] in {"executing", "completed"} for s in begun["steps"])
    assert any(s.get("depends_on") and s["status"] == "waiting" for s in begun["steps"])
    at = clock["t"]
    with operations.SessionLocal() as db:
        assert len(list(db.scalars(select(DrillCommand)))) == 2  # Residents and movement, no early broadcast.
        advance_run(db, db.get(AgentRun, run["id"]), SimpleNamespace(username="admin"))
        assert len(list(db.scalars(select(DrillCommand)))) == 2
    for _ in range(10):
        data = tick(clock["t"] + 20)
        with operations.SessionLocal() as db:
            record = db.get(AgentRun, run["id"])
            advance_run(db, record, SimpleNamespace(username="admin"))
            if record.status == "awaiting_rollcall":
                break
    else:
        raise AssertionError("Joint robot/resident workflow did not finish: " + record.reason)
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run["id"])
        advance_run(db, record, SimpleNamespace(username="admin"))
        broadcasts = list(db.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == demo["drill_id"], DrillEvent.event_type == "robot.broadcast_completed")))
        assert len(broadcasts) == 1
        assert broadcasts[0].elapsed_seconds >= at + candidate["robot_support"]["duration_seconds"]
        assert len(list(db.scalars(select(DrillCommand)))) == 3
        assert all(s["status"] == "completed" for s in record.steps)
        evidence = completed_broadcast(db, record)
        assert evidence == broadcasts[0].id
        from app.models.operations import DrillSession
        drill = db.get(DrillSession, demo["drill_id"])
        current = operations.snapshot(db, drill)
        support, extra_steps = robot_support(operations, db, drill, current, {**record.scope, "robot_broadcast_evidence": evidence})
        assert support["already_completed"] and extra_steps == []


def test_robot_manual_cancellation_yields_automatic_control(exercise):
    client, headers, _, root, *_ = exercise
    run, candidate = robot_proposal(exercise)
    approved = client.post(root + '/agent/runs/' + run["id"] + '/actions', headers=headers, json={
        "action": "approve", "revision": 1, "candidate_id": candidate["id"]})
    assert approved.status_code == 200, approved.text
    current = client.get(root, headers=headers).json()
    task = next(t for t in current["robot"]["task_queue"] if t["status"] == "executing")
    cancelled = client.post(root + '/robot', headers=headers, json={"command": "cancel", "task_id": task["id"]})
    assert cancelled.status_code == 200, cancelled.text
    with operations.SessionLocal() as db:
        record = db.get(AgentRun, run["id"])
        advance_run(db, record, SimpleNamespace(username="admin"))
        assert record.status == "taken_over"
        assert not any(c.command_args.get("command") == "broadcast" for c in db.scalars(select(DrillCommand)))


def test_no_staff_cannot_approve_escort(exercise):
    client, headers, demo, root, _, _, _, _, start = exercise
    with operations.SessionLocal() as db:
        created = db.scalar(select(DrillEvent).where(DrillEvent.drill_session_id == demo["drill_id"], DrillEvent.event_type == "drill.created"))
        payload = deepcopy(created.payload)
        payload["world"]["response_staff"] = []
        created.payload = payload; db.commit()
    data = start()
    resident = next(p for p in data["simulation"]["residents"] if p["vulnerable"])
    run = proposal(client, headers, root, [resident["id"]])
    assert all(not c["can_apply"] and c["assist_resource"]["capacity"] == 0 for c in run["candidates"])
    response = client.post(root + '/agent/runs/' + run["id"] + '/actions', headers=headers,
        json={"action": "approve", "revision": 1, "candidate_id": run["candidates"][0]["id"]})
    assert response.status_code == 409
    with operations.SessionLocal() as db:
        assert not list(db.scalars(select(DrillCommand)))


def test_stopped_plan_keeps_live_receipts_and_unchecked_end_is_unfinished(exercise):
    client, headers, demo, root, _, _, clock, tick, start = exercise
    data = start()
    resident = next(p for p in data["simulation"]["residents"] if not p["vulnerable"])
    run = proposal(client, headers, root, [resident["id"]])
    candidate = next(c for c in run["candidates"] if c["can_apply"])
    url = root + '/agent/runs/' + run["id"] + '/actions'
    assert client.post(url, headers=headers, json={"action":"approve","revision":1,"candidate_id":candidate["id"]}).status_code == 200
    assert client.post(url, headers=headers, json={"action":"stop","revision":1}).status_code == 200
    tick(clock["t"] + 60)
    view = client.get(root + '/agent/runs', headers=headers).json()["runs"][0]
    assert view["status"] == "stopped"
    with operations.SessionLocal() as db:
        receipt = db.scalar(select(DrillCommand).where(DrillCommand.command_id == view["steps"][0]["command_id"]))
        assert view["steps"][0]["progress"] == receipt.progress
        assert view["steps"][0]["status"] == receipt.status
        assert not view["steps"][0]["execution"]["stalled"]
        from app.models.operations import DrillSession
        drill = db.get(DrillSession, demo["drill_id"])
        record = db.get(AgentRun, run["id"])
        record.status = "awaiting_rollcall"; drill.status = "ended"; db.commit()
        reconcile_rollcall(db, record, SimpleNamespace(username="admin"))
        assert record.status == "unfinished"


def test_ready_robot_plan_replans_after_system_inspection_without_takeover(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    ready = client.get(root, headers=headers).json()
    resident = next(person for person in ready["simulation"]["residents"] if not person["vulnerable"])
    created = client.post(root + "/agent/runs", headers=headers, json={
        "request_id": "ready-inspection-plan-0001",
        "goal": "将本楼居民疏散并安排机器人楼门广播",
        "resident_ids": [resident["id"]],
        "priority_assist": False,
        "robot_broadcast": True,
    })
    assert created.status_code == 201, created.text
    assert not any(candidate["can_apply"] for candidate in created.json()["candidates"])
    start()
    refreshed = client.post(root + "/agent/runs/" + created.json()["id"] + "/actions", headers=headers, json={
        "action": "replan", "revision": 1,
    })
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["status"] == "awaiting_approval"
    assert any(candidate["can_apply"] for candidate in refreshed.json()["candidates"])


def test_cross_building_robot_broadcast_is_compiled_as_sequential_tasks(exercise):
    client, headers, _, root, _, _, _, _, start = exercise
    data = start()
    residents = [person for person in data["simulation"]["residents"] if not person["vulnerable"]]
    building_ids = {person.get("building_id") for person in residents if person.get("building_id")}
    assert len(building_ids) >= 2
    created = client.post(root + "/agent/runs", headers=headers, json={
        "request_id": "cross-building-plan-0001",
        "goal": "组织多栋居民疏散并逐栋安排机器人楼门广播",
        "resident_ids": [person["id"] for person in residents],
        "priority_assist": False,
        "robot_broadcast": True,
    })
    assert created.status_code == 201, created.text
    candidate = next(item for item in created.json()["candidates"] if item["can_apply"])
    assert candidate["robot_support"]["target_count"] == len(building_ids)
    approved = client.post(root + "/agent/runs/" + created.json()["id"] + "/actions", headers=headers, json={
        "action": "approve", "revision": 1, "candidate_id": candidate["id"],
    })
    assert approved.status_code == 200, approved.text
    robot_steps = [step for step in approved.json()["steps"] if step.get("kind") == "robot.command"]
    assert len(robot_steps) == len(building_ids) * 2
    for index in range(2, len(robot_steps), 2):
        assert robot_steps[index - 1]["id"] in robot_steps[index]["depends_on"]


def test_end_state_synchronously_freezes_completed_agent_result(exercise):
    client, headers, _, root, public, code, clock, tick, start = exercise
    data = start()
    resident = next(person for person in data["simulation"]["residents"] if not person["vulnerable"])
    run = proposal(client, headers, root, [resident["id"]], "end-freeze-plan-0001")
    candidate = next(item for item in run["candidates"] if item["can_apply"])
    action_url = root + "/agent/runs/" + run["id"] + "/actions"
    assert client.post(action_url, headers=headers, json={"action": "approve", "revision": 1, "candidate_id": candidate["id"]}).status_code == 200
    for _ in range(8):
        tick(clock["t"] + 30)
        with operations.SessionLocal() as db:
            record = db.get(AgentRun, run["id"])
            advance_run(db, record, SimpleNamespace(username="admin"))
            if record.status == "awaiting_rollcall":
                break
    member = client.post(public + "/join?code=" + code, json={"role": "居民代表", "display_name": "收尾清点员"}).json()
    counted = client.post(public + "/actions?code=" + code, json={
        "role": "居民代表", "action": "resident_counted", "message": "结束前逐人核验完成",
        "participant_token": member["token"], "resident_ids": [resident["id"]],
    })
    assert counted.status_code == 200, counted.text
    ended = client.patch(root + "/state", headers=headers, json={"action": "end"})
    assert ended.status_code == 200, ended.text
    final = client.get(root + "/agent/runs", headers=headers).json()["runs"][0]
    assert final["status"] == "completed"
    assert all(step["status"] == "completed" for step in final["steps"])
