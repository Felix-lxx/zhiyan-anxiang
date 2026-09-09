from types import SimpleNamespace

import pytest

from app.api.routes.operations import robot_runtime
from app.services.drill_simulation import plan_route, simulate_residents


@pytest.fixture
def road_graph():
    nodes = [
        {"id": "n", "name": "北门", "x": 12, "y": 12, "is_exit": True},
        {"id": "a", "name": "西路口", "x": 34, "y": 48, "is_exit": False},
        {"id": "b", "name": "楼栋路口", "x": 58, "y": 48, "is_exit": False},
        {"id": "c", "name": "东路口", "x": 84, "y": 48, "is_exit": False},
        {"id": "s", "name": "南门", "x": 84, "y": 88, "is_exit": True},
    ]
    by_id = {node["id"]: node for node in nodes}
    edges = []
    for a, b in [("n", "a"), ("a", "b"), ("b", "c"), ("c", "s")]:
        edges.append({"id": a + b, "name": "南门道路" if b == "s" else a + b, "start_node_id": a, "end_node_id": b, "start": {"x": by_id[a]["x"], "y": by_id[a]["y"]}, "end": {"x": by_id[b]["x"], "y": by_id[b]["y"]}, "width_meters": 3, "status": "open", "blocked_by_event": False, "risk_score": 0})
    return {"nodes": nodes, "edges": edges}


def event(kind, at, payload, sequence=1):
    return {"sequence": sequence, "elapsed_seconds": at, "event_type": kind, "payload": payload}


def test_indoor_stages_follow_notification_and_stair_capacity(road_graph):
    def world(count):
        return {"fire_origin": {"x": 66, "y": 43}, "robot_origin": {"x": 34, "y": 48},
                "residents": [{"id": f"resident-{i+1}", "x": 58, "y": 48, "building_id": "home",
                               "floor": 3, "current_floor": 3.0, "indoor_remaining": 18.0,
                               "preparation_seconds": 3, "indoor_stage": "room", "vulnerable": False} for i in range(count)]}
    notice = event('robot.broadcast_completed', 10, {})
    assert all(p['indoor_stage'] == 'room' for p in simulate_residents(road_graph, [notice], 9, world=world(6))['residents'])
    prepared = simulate_residents(road_graph, [notice], 12, world=world(6))
    assert all(p['indoor_stage'] == 'preparing' for p in prepared['residents'])
    stairs = simulate_residents(road_graph, [notice], 17, world=world(6))
    assert all(p['indoor_stage'] == 'stairs' and p['travelled'] == 0 for p in stairs['residents'])
    single = simulate_residents(road_graph, [notice], 17, world=world(1))
    assert stairs['residents'][0]['current_floor'] > single['residents'][0]['current_floor']
    final = simulate_residents(road_graph, [notice], 240, world=world(6))
    assert final['summary']['evacuated'] == 6
    assert all(p['building_exited_at_seconds'] > 13 for p in final['residents'])
    assert stairs == simulate_residents(road_graph, [notice], 17, world=world(6))


def test_changing_exit_preserves_existing_assistance(road_graph):
    commands = [event('resident.command', 0, {'resident_ids': ['resident-3'], 'exit': 'north', 'action': 'priority_assist'}),
                event('resident.command', 1, {'resident_ids': ['resident-3'], 'exit': 'south', 'action': 'evacuate'}, 2)]
    result = simulate_residents(road_graph, commands, 1)
    assert result['residents'][2]['assisted'] and result['residents'][2]['exit'] == 'south'


def test_commands_preserve_position_and_smoke_is_cumulative(road_graph):
    before = simulate_residents(road_graph, [], 20)
    command = event("resident.command", 20, {"resident_ids": ["resident-3"], "exit": "north", "action": "priority_assist"})
    immediate = simulate_residents(road_graph, [command], 20)
    assert immediate["residents"][2]["x"] == before["residents"][2]["x"]
    assert immediate["residents"][2]["y"] == before["residents"][2]["y"]
    assert immediate["residents"][2]["assisted"] is True
    later = simulate_residents(road_graph, [command], 30)
    assert later["residents"][2]["travelled"] > immediate["residents"][2]["travelled"]
    assert later["residents"][2]["smoke_exposure"] >= immediate["residents"][2]["smoke_exposure"]
    assert later == simulate_residents(road_graph, [command], 30)


def test_block_applies_at_event_time_and_replay_does_not_leak_future(road_graph):
    block = event("inject.channel_blocked", 20, {"blocked_edge_id": "cs", "x": 84, "y": 68})
    before = simulate_residents(road_graph, [block], 19)
    assert next(edge for edge in before["road_network"]["edges"] if edge["id"] == "cs")["status"] == "open"
    initial = simulate_residents(road_graph, [], 20)
    after = simulate_residents(road_graph, [block], 20)
    assert [(p["x"], p["y"]) for p in initial["residents"]] == [(p["x"], p["y"]) for p in after["residents"]]
    assert all("cs" not in person["route_edge_ids"] for person in after["residents"])
    _, points, _, _, _ = plan_route(after["road_network"], (58, 48), (84, 88), 20)
    assert len(points) == 1


def test_parallel_worlds_share_history_then_diverge(road_graph):
    block = event("inject.channel_blocked", 20, {"blocked_edge_id": "cs", "x": 84, "y": 68})
    left_start = simulate_residents(road_graph, [block], 20, "south_standard", 20)
    right_start = simulate_residents(road_graph, [block], 20, "north_priority", 20)
    assert [(p["x"], p["y"]) for p in left_start["residents"]] == [(p["x"], p["y"]) for p in right_start["residents"]]
    left = simulate_residents(road_graph, [block], 110, "south_standard", 20)
    right = simulate_residents(road_graph, [block], 110, "north_priority", 20)
    assert any(not p["route_reachable"] for p in left["residents"])
    assert right["summary"]["evacuated"] > left["summary"]["evacuated"]


def test_mobile_rollcall_and_resources_change_the_world(road_graph):
    missing = event("inject.resident_missing", 5, {})
    assert simulate_residents(road_graph, [missing], 10)["summary"]["missing"] == 1
    counted = event("participant.resident_counted", 10, {}, 2)
    resources = event("participant.resource_ready", 10, {}, 3)
    result = simulate_residents(road_graph, [missing, counted, resources], 20)
    assert result["summary"]["missing"] == 0
    assert result["environment"]["resource_ready"] is True
    assert result["fire"]["intensity"] < simulate_residents(road_graph, [missing], 20)["fire"]["intensity"]


def robot_event(event_id, sequence, start, end, at=0, kind="robot.target_assigned", **payload):
    return SimpleNamespace(id=event_id, sequence=sequence, elapsed_seconds=at, event_type=kind, message=event_id, payload={"target": event_id, "route": ["road"], "route_points": [{"x": start, "y": 0}, {"x": end, "y": 0}], "route_edge_ids": ["road"], "planned_duration_seconds": 10, **payload})


def test_robot_tasks_run_sequentially_and_replans_start_at_current_position():
    robot = SimpleNamespace(id="r", name="robot", x=0, y=0, battery=100, route=[], current_task=None, reason="", state="executing")
    first = robot_event("t1", 1, 0, 10)
    second = robot_event("t2", 2, 10, 20)
    at5 = robot_runtime(robot, [first, second], 5)
    assert at5["x"] == 5
    assert [task["status"] for task in at5["task_queue"]] == ["executing", "queued"]
    assert at5["task_queue"][1]["progress"] == 0
    assert robot_runtime(robot, [first, second], 15)["x"] == 15
    assert robot_runtime(robot, [first, second], 20)["state"] == "arrived"
    cancelled = SimpleNamespace(id="c2", sequence=3, elapsed_seconds=0, event_type="robot.task_cancelled", message="cancel", payload={"target_event_id": "t2", "x": 0, "y": 0})
    assert robot_runtime(robot, [first, second, cancelled], 10)["x"] == 10
    replan = robot_event("p1", 3, 5, 10, at=5, kind="robot.replanned", target_event_id="t1")
    assert robot_runtime(robot, [first, second, replan], 5)["x"] == 5
    assert robot_runtime(robot, [first, second, replan], 10)["task_queue"][1]["status"] == "queued"


def test_unreachable_robot_task_never_auto_completes():
    robot = SimpleNamespace(id="r", name="robot", x=0, y=0, battery=100, route=[], current_task=None, reason="", state="executing")
    blocked = robot_event("t1", 1, 0, 10, route_points=[{"x": 0, "y": 0}])
    live = robot_runtime(robot, [blocked], 300)
    assert live["state"] == "blocked"
    assert live["task_queue"][0]["progress"] == 0
    assert live["x"] == 0
