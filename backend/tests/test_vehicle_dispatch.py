from copy import deepcopy
from types import SimpleNamespace
import json

from app.services.vehicle_dispatch import fleet, plan_vehicle, vehicle_runtime
from app.services.realtime import snapshot_patch
from test_exercise_world import exercise


def test_vehicle_segment_stop_resume_and_width():
    nodes = [{"id": key, "name": key, "x": x, "y": 0, "is_exit": key == "a"} for key, x in [("a", 0), ("b", 12), ("c", 24)]]
    edges = [{"id": a + b, "start_node_id": a, "end_node_id": b, "status": "open", "width_meters": 4, "risk_score": 0} for a, b in [("a", "b"), ("b", "c")]]
    world = {"road_network": {"nodes": nodes, "edges": edges}}
    vehicle = fleet(world)[0]
    plan = plan_vehicle(world["road_network"], vehicle, "c")
    assert plan["can_apply"] and plan["planned_duration_seconds"] == 10
    event = SimpleNamespace(id="mission", sequence=1, elapsed_seconds=0, event_type="vehicle.dispatched", payload={**plan, "vehicle_id": vehicle["id"]})
    moving = vehicle_runtime(world, [event], 2)[0]
    assert 0 < moving["x"] < 12 and moving["current_edge_id"] == "ab"
    closed = deepcopy(world["road_network"]); closed["edges"][0]["status"] = "blocked"
    stop_plan = plan_vehicle(closed, moving, "c")
    assert not stop_plan["can_apply"]
    stop = SimpleNamespace(id="stop", sequence=2, elapsed_seconds=2, event_type="vehicle.replanned", payload={**stop_plan, "vehicle_id": vehicle["id"], "mission_id": "mission"})
    blocked = vehicle_runtime(world, [event, stop], 20)[0]
    assert blocked["state"] == "blocked" and blocked["x"] == moving["x"]
    resumed = plan_vehicle(world["road_network"], blocked, "c")
    assert resumed["can_apply"] and resumed["route_points"][0]["x"] == moving["x"]
    go = SimpleNamespace(id="go", sequence=3, elapsed_seconds=20, event_type="vehicle.replanned", payload={**resumed, "vehicle_id": vehicle["id"], "mission_id": "mission"})
    final = vehicle_runtime(world, [event, stop, go], 100)[0]
    assert final["state"] == "arrived" and final["x"] == 24 and final["missions"][0]["status"] == "completed"
    narrow = deepcopy(world["road_network"]); narrow["edges"][0]["width_meters"] = 3
    assert not plan_vehicle(narrow, vehicle, "c")["can_apply"]
    assert plan_vehicle(narrow, fleet(world)[1], "c")["can_apply"]


def test_vehicle_commands_are_durable_idempotent_and_record_arrival(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    state = start()
    vehicle = state["simulation"]["vehicles"][0]
    plan = next(p for node in state["simulation"]["road_network"]["nodes"]
                if (p := plan_vehicle(state["simulation"]["road_network"], vehicle, node["id"]))["can_apply"] and p["planned_duration_seconds"] > 0)
    payload = {"command_id": "vehicle-test-001", "kind": "vehicle.command", "arguments": {"vehicle_id": vehicle["id"], "command": "dispatch", "target_node_id": plan["target_node_id"]}}
    preview = client.post(root + '/vehicles/preview', headers=headers, json=payload["arguments"])
    assert preview.status_code == 200 and preview.json()["can_apply"]
    result = client.post(root + '/commands', headers=headers, json=payload)
    assert result.status_code == 200, result.text
    accepted = result.json(); began = clock["t"]
    assert accepted["commands"][0]["status"] == "executing"
    retry = client.post(root + '/commands', headers=headers, json=payload).json()
    assert retry["latest_event_sequence"] == accepted["latest_event_sequence"]
    moving = tick(began + 1)["simulation"]["vehicles"][0]
    closed = client.post(root + '/inject', headers=headers, json={"event_type": "channel_blocked", "road_edge_id": moving["current_edge_id"]})
    assert closed.status_code == 200, closed.text
    assert closed.json()["simulation"]["vehicles"][0]["state"] == "blocked"
    stopped = tick(began + 4)["simulation"]["vehicles"][0]
    assert (stopped["x"], stopped["y"]) == (moving["x"], moving["y"])
    reopened = client.post(root + '/roads/' + moving["current_edge_id"] + '/reopen', headers=headers)
    assert reopened.status_code == 200, reopened.text
    remaining = reopened.json()["simulation"]["vehicles"][0]["remaining_seconds"]
    complete = tick(clock["t"] + remaining + 1)
    assert complete["simulation"]["vehicles"][0]["state"] == "arrived"
    assert complete["commands"][0]["status"] == "completed"
    assert len([e for e in complete["events"] if e["event_type"] == "vehicle.arrived"]) == 1
    assert client.get(root, headers=headers).json()["simulation"]["vehicles"] == complete["simulation"]["vehicles"]
    historic = client.get(root + f'/replay?at_seconds={began}', headers=headers).json()
    assert historic["simulation"]["vehicles"][0]["progress"] == 0
    clock["t"] = began  # Fixture clock substitutes effective_elapsed for both source and paused fork.
    branch = client.post(root + '/branches', headers=headers, json={"at_seconds": began, "name": "车辆分支验收"})
    assert branch.status_code == 201, branch.status_code
    assert branch.json()["simulation"]["vehicles"][0]["state"] == "moving"
    original_ids = {e["id"] for e in accepted["events"]}
    branch_vehicle = branch.json()["simulation"]["vehicles"][0]
    assert branch_vehicle["mission_id"] not in original_ids
    assert client.patch(root + '/state', headers=headers, json={"action": "pause"}).status_code == 200
    assert client.post(root + '/vehicles', headers=headers, json=payload["arguments"]).status_code == 409


def test_population_delta_only_transmits_changed_fields():
    old = {"simulation": {"residents": [{"id": str(i), "x": 0, "label": f"居民{i}", "route_points": [{"x": j, "y": j} for j in range(20)]} for i in range(1000)]}}
    new = deepcopy(old); new["simulation"]["residents"][42]["x"] = 1
    patch = snapshot_patch(old, new, entities=True)
    assert patch[0]["entities"]["updated"] == [{"id": "42", "set": {"x": 1}, "unset": []}]
    assert len(json.dumps(patch)) < len(json.dumps(new)) / 100
    assert "value" in snapshot_patch(old, new)[0]  # Existing protocol 2 remains compatible.
