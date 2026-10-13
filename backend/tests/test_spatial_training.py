from copy import deepcopy
import math

from test_exercise_world import exercise
from test_drill_simulation import road_graph, event
from app.api.routes import operations
from app.services.spatial_world import add_spatial_layout
from app.services.spatial_simulation import simulate, xyz


def layout(roads, count=12, width=1.2):
    home = dict(id="home", x=58, y=40, width=10, depth=8, floors=3, entry={"x": 58, "y": 48})
    people = [dict(id=f"resident-{i+1}", label=f"居民{i+1}", vulnerable=i==2, floor=3, current_floor=3., indoor_stage="room", preparation_seconds=0, building_id="home") for i in range(count)]
    return add_spatial_layout(dict(parameters={"south_lane_status": "open", "hydrant_status": "available", "stair_width": width}, residents=people, road_network=deepcopy(roads), fire_origin={"x": 66, "y": 43}, robot_origin={"x": 34, "y": 48}), home)


def test_dormant_session_fast_forward_preserves_exposure_and_late_commands(road_graph):
    world = layout(road_graph, 1)
    base = simulate(world, [], 200)["residents"][0]
    later = simulate(world, [], 2_000_000)["residents"][0]
    density = max(0., 1-math.dist(xyz(base), (66, 43, 0))/48)
    assert math.isclose(later["smoke_exposure"]-base["smoke_exposure"], density*.85*(2_000_000-200), abs_tol=1e-6)
    assert xyz(later) == xyz(base)
    assert later["status"] == "waiting"
    command = event("robot.broadcast_completed", 2_000_000, {})
    result = simulate(world, [command], 2_000_300)["residents"][0]
    assert result["status"] == "evacuated"
    assert result["assembly_arrived_at_seconds"] >= 2_000_000


def test_opening_drill_does_not_advance_or_wait_for_engine(exercise, monkeypatch):
    client, headers, _, root, *_ = exercise
    def unexpected(*args, **kwargs):
        raise AssertionError("GET must not acquire the engine command lock")
    monkeypatch.setattr(operations, "advance_engine", unexpected)
    response = client.get(root, headers=headers)
    assert response.status_code == 200
    assert response.json()["simulation"]["residents"]


def test_continuous_room_stair_door_exit_and_assembly(road_graph):
    world = layout(road_graph, 1)
    history = [event("robot.broadcast_completed", 0, {})]
    previous, stages = None, set()
    for t in range(150):
        p = simulate(world, history, t)["residents"][0]
        stages.add(p["indoor_stage"])
        if previous: assert math.dist(xyz(previous), xyz(p)) <= 1.31
        previous = p
    assert {"room", "corridor", "stairs", "door", "outdoor"}.issubset(stages)
    assert p["status"] == "evacuated"
    assert p["assembly_arrived_at_seconds"] > p["exit_reached_at_seconds"] > p["building_exited_at_seconds"]
    assert p["counted"] is False


def test_capacity_headway_and_narrow_stair_queue(road_graph):
    history = [event("robot.broadcast_completed", 0, {})]
    narrow, wide = layout(road_graph, 24, .6), layout(road_graph, 24, 2.4)
    a, b = simulate(narrow, history, 55), simulate(wide, history, 55)
    assert sum(p["queue_seconds"] for p in a["residents"]) > sum(p["queue_seconds"] for p in b["residents"])
    assert sum(p["travelled"] for p in a["residents"]) < sum(p["travelled"] for p in b["residents"])
    narrow_stairs = [edge for edge in a["spatial_network"]["edges"] if edge["kind"] == "stairs"]
    wide_stairs = [edge for edge in b["spatial_network"]["edges"] if edge["kind"] == "stairs"]
    assert max(edge["density_percent"] for edge in narrow_stairs) >= max(edge["density_percent"] for edge in wide_stairs)
    assert all({"capacity_persons", "live_occupancy", "waiting_count", "flow_capacity_per_second", "risk_score"} <= edge.keys() for edge in narrow_stairs)
    for t in (8, 12, 20, 35):
        persons = simulate(narrow, history, t)["residents"]
        for i, p in enumerate(persons):
            for q in persons[i+1:]:
                if p["edge_id"] and p["edge_id"] == q["edge_id"] and p["lane"] == q["lane"]:
                    assert abs(p["edge_progress"]-q["edge_progress"]) >= .79


def test_helper_really_enters_and_meets_before_resident_moves(road_graph):
    world = layout(road_graph, 3)
    command = event("resident.command", 0, {"resident_ids": ["resident-3"], "exit": "north", "action": "priority_assist"})
    first = simulate(world, [command], 1)
    assert not first["residents"][2]["assisted"]
    assert xyz(first["residents"][2]) == xyz(world["residents"][2])
    midway = simulate(world, [command], 35)
    assert midway["helpers"][0]["height"] > 0
    final = simulate(world, [command], 230)
    assert final["helpers"][0]["met_at_seconds"] > 1
    assert final["helpers"][0]["state"] == "completed"
    assert final["residents"][2]["assisted"]


def test_block_occupied_segment_retreats_without_teleport(road_graph):
    world = layout(road_graph, 1)
    history = [event("robot.broadcast_completed", 0, {})]
    state = simulate(world, history, 45)["residents"][0]
    assert state["edge_id"]
    history.append(event("inject.channel_blocked", 45, {"blocked_edge_id": state["edge_id"]}, 2))
    same = simulate(world, history, 45)["residents"][0]
    next_person = simulate(world, history, 46)["residents"][0]
    assert xyz(same) == xyz(state)
    assert math.dist(xyz(next_person), xyz(state)) <= 1.31
    assert next_person["edge_progress"] < state["edge_progress"]


def test_shared_preview_parameters_and_no_mutation(exercise):
    client, headers, demo, root, _, _, clock, tick, _ = exercise
    original = tick(0)["simulation"]["world"]
    params = {**original["parameters"], "resident_count": 9, "stair_width": .7, "hydrant_status": "available", "south_lane_status": "blocked"}
    response = client.patch('/api/v1/scenes/'+demo["scene_id"]+'/charging-shed-parameters', headers=headers, json=params)
    assert response.status_code == 200, response.text
    preview = client.get('/api/v1/scenes/'+demo["scene_id"]+'/preview?minute=0', headers=headers).json()["simulation"]
    # Editing a published scene derives a draft version. Freeze that revision
    # before creating a drill so preview and runtime use the same model.
    assert client.post('/api/v1/scenes/'+demo["scene_id"]+'/validate', headers=headers).json()["passed"] is True
    assert client.post('/api/v1/scenes/'+demo["scene_id"]+'/publish', headers=headers).status_code == 200
    new = client.post('/api/v1/scenes/'+demo["scene_id"]+'/drills', headers=headers, json={"name": "统一模型验证"}).json()
    assert new["simulation"] == preview
    assert preview["summary"]["total"] == 9
    assert preview["environment"]["east_hydrant"] == "available"
    assert preview["environment"]["south_lane"] == "blocked"
    assert tick(0)["simulation"]["world"] == original
    route_preview = client.post(root+'/residents/preview', headers=headers, json={"resident_ids":["resident-1"], "exit":"north"})
    assert route_preview.status_code == 200
    assert route_preview.json()["residents"][0]["route_points"][0]["height"] > 0
    assert route_preview.json()["kind"] == "residents"
    assert route_preview.json()["impact"]["forecast_horizon_seconds"] == 30
    assert route_preview.json()["expected_sequence"] == tick(0)["latest_event_sequence"]
    assert "delta" in route_preview.json()["score_impact"]
    assert not any(e["event_type"] == "resident.command" for e in tick(0)["events"])


def test_spatial_action_previews_are_non_mutating(exercise):
    client, headers, _, root, _, _, _, tick, _ = exercise
    client.patch(root+'/state', headers=headers, json={"action":"start"})
    before = tick(0)
    road = next(edge for edge in before["simulation"]["road_network"]["edges"] if edge["status"] != "blocked")
    road_preview = client.get(root+f'/roads/{road["id"]}/preview-block', headers=headers)
    assert road_preview.status_code == 200, road_preview.text
    assert road_preview.json()["kind"] == "road"
    assert road_preview.json()["impact"]["forecast_horizon_seconds"] == 30
    assert road_preview.json()["expected_sequence"] == before["latest_event_sequence"]
    assert "delta" in road_preview.json()["score_impact"]
    robot_preview = client.post(root+'/robot/preview', headers=headers, json={"command":"move","x":58,"y":54,"target":"3号楼入口"})
    assert robot_preview.status_code == 200, robot_preview.text
    assert robot_preview.json()["kind"] == "robot"
    assert robot_preview.json()["route_points"]
    assert robot_preview.json()["expected_sequence"] == before["latest_event_sequence"]
    assert robot_preview.json()["score_impact"]["delta"] == 0
    after = tick(0)
    assert len(after["events"]) == len(before["events"])
    assert not any(event["event_type"] == "inject.channel_blocked" and event["payload"].get("blocked_edge_id") == road["id"] for event in after["events"])


def test_only_arrival_allows_rollcall_and_search_is_physical(exercise):
    client, headers, demo, root, _, _, clock, tick, _ = exercise
    client.patch(root+'/state', headers=headers, json={"action":"start"})
    body = {"role":"居民代表", "action":"resident_counted", "message":"集合点核验居民身份", "resident_ids":["resident-3"]}
    assert client.post(root+'/participant-actions', headers=headers, json=body).status_code == 409
    search = client.post(root+'/searches', headers=headers, json={"resident_id":"resident-3", "responsible":"物业搜索员甲"})
    assert search.status_code == 200, search.text
    p = search.json()["simulation"]["residents"][2]
    assert p["status"] == "missing" and p["search_responsible"] == "物业搜索员甲"
    assert client.post(root+'/searches', headers=headers, json={"resident_id":"resident-3", "responsible":"另一名人员"}).status_code == 409
    final = tick(400)
    assert final["simulation"]["residents"][2]["status"] == "evacuated"
    assert client.post(root+'/participant-actions', headers=headers, json=body).json()["simulation"]["residents"][2]["counted"]
    assert not tick(400)["simulation"]["residents"][0]["counted"]


def test_editable_fork_uses_exact_prefix_same_second_and_isolated_history(exercise, monkeypatch):
    client, headers, demo, root, _, _, clock, tick, _ = exercise
    monkeypatch.setattr(operations, "effective_elapsed", lambda d: clock["t"] if d.status == "running" else d.elapsed_seconds)
    client.patch(root+'/state', headers=headers, json={"action":"start"})
    clock["t"] = 10
    command = client.post(root+'/residents', headers=headers, json={"resident_ids":["resident-1"],"exit":"north"}).json()
    original_people = command["simulation"]["residents"]
    edge = command["simulation"]["road_network"]["edges"][0]
    blocked = client.post(root+'/inject', headers=headers, json={"event_type":"channel_blocked","road_edge_id":edge["id"]}).json()
    decision = next(e for e in blocked["events"] if e["event_type"] == "inject.channel_blocked")
    clock["t"] = 20
    fork = client.post(root+'/branches', headers=headers, json={"at_seconds":10,"before_sequence":decision["sequence"],"name":"北路封锁前重做"})
    assert fork.status_code == 201, fork.text
    child = fork.json(); child_root='/api/v1/drills/'+child["id"]
    assert child["status"] == "paused" and child["elapsed_seconds"] == 10
    assert child["simulation"]["residents"] == original_people
    assert any(e["event_type"] == "resident.command" for e in child["events"])
    assert not any(e["event_type"] == "inject.channel_blocked" for e in child["events"])
    clock["t"] = 10
    client.patch(child_root+'/state', headers=headers, json={"action":"resume"})
    assert client.post(child_root+'/residents', headers=headers, json={"resident_ids":["resident-1"],"exit":"south"}).status_code == 200
    clock["t"] = 50
    compared = client.get(child_root+'/branch-comparison', headers=headers).json()
    assert compared["at_seconds"] == 50
    assert compared["worlds"]["baseline"]["residents"][0]["exit"] == "north"
    assert compared["worlds"]["alternative"]["residents"][0]["exit"] == "south"
    assert {p["id"] for p in compared["residents"]} == {p["id"] for p in original_people}
    assert client.post(root+'/branches', headers=headers, json={"at_seconds":1000}).status_code == 422


def test_fire_controls_change_smoke_not_just_labels(road_graph):
    world = layout(road_graph, 1)
    untouched = simulate(world, [], 20)
    controlled = simulate(world, [event('task.completed',0,{"kind":"power_off"})],20)
    assert controlled["fire"]["smoke_radius"] < untouched["fire"]["smoke_radius"]
    assert controlled["fire"]["intensity"] < untouched["fire"]["intensity"]
