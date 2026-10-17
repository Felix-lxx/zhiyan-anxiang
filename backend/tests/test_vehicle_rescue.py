from types import SimpleNamespace

from app.services.fire_environment import EnvironmentTimeline
from app.services.vehicle_dispatch import plan_vehicle, vehicle_runtime, fleet
from app.services.vehicle_rescue import action_plan
from app.services.vehicle_traffic import TrafficTimeline, protect_plan
from test_exercise_world import exercise


def test_water_effect_expiry_failure_and_stop():
    world = {"parameters": {}}
    spray = {"sequence": 1, "elapsed_seconds": 20, "event_type": "vehicle.action_started", "payload": {"action_id": "water", "action": "spray", "duration_seconds": 45}}
    baseline = EnvironmentTimeline(world, [])
    wet = EnvironmentTimeline(world, [spray])
    assert wet.at(30)[0]["intensity"] < baseline.at(30)[0]["intensity"]
    assert wet.at(30)[0]["smoke_radius"] < baseline.at(30)[0]["smoke_radius"]
    assert wet.at(65)[0]["intensity"] == 0 and not wet.at(65)[1]["water_suppression"]
    assert wet.at(80)[0]["intensity"] == 0
    for kind in ["inject.hydrant_failure", "vehicle.action_stopped"]:
        stop = {"sequence": 2, "elapsed_seconds": 22, "event_type": kind, "payload": {"action_id": "water"}}
        interrupted = EnvironmentTimeline(world, [spray, stop])
        assert not interrupted.at(23)[1]["water_suppression"]
        assert interrupted.at(30)[0]["intensity"] > interrupted.at(22)[0]["intensity"]


def test_corridor_interlock_waits_then_releases_without_teleport():
    world = {"road_network": {"nodes": [{"id": "a", "name": "入口", "x": 0, "y": 0, "is_exit": True}, {"id": "b", "name": "现场", "x": 12, "y": 0, "is_exit": False}],
                              "edges": [{"id": "ab", "start_node_id": "a", "end_node_id": "b", "width_meters": 4, "status": "open", "live_occupancy": 2}]}}
    vehicle = fleet(world)[0]
    same_node = protect_plan(plan_vehicle(world["road_network"], vehicle, "a"), {"vehicles": [vehicle], "road_network": world["road_network"]}, vehicle["id"])
    assert not same_node["can_apply"] and "已经在该节点" in same_node["notice"]
    plan = protect_plan(plan_vehicle(world["road_network"], vehicle, "b"), {"vehicles": [vehicle], "road_network": world["road_network"]}, vehicle["id"])
    assert plan["hold_for_pedestrians"] and plan["yielding_people"] == 2
    dispatch = SimpleNamespace(id="mission", sequence=1, elapsed_seconds=0, event_type="vehicle.dispatched", payload={**plan, "vehicle_id": vehicle["id"]})
    assert vehicle_runtime(world, [dispatch], 10)[0]["x"] == 0
    assert vehicle_runtime(world, [dispatch], 10)[0]["state"] == "yielding"
    release = SimpleNamespace(id="go", sequence=2, elapsed_seconds=10, event_type="vehicle.traffic_released", payload={"vehicle_id": vehicle["id"], "mission_id": "mission", "planned_duration_seconds": plan["planned_duration_seconds"]})
    traffic = TrafficTimeline([vars(dispatch), vars(release)])
    assert traffic.at(9) == {"ab": vehicle["id"]}
    assert traffic.at(15) == {}
    moving = vehicle_runtime(world, [dispatch, release], 11)[0]
    assert moving["state"] == "moving" and 0 < moving["x"] < 12


def test_spraying_is_a_timed_command_with_real_environment_and_replay(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    state = start()["simulation"]
    vehicle = state["vehicles"][0]
    plans = [plan_vehicle(state["road_network"], vehicle, n["id"]) for n in state["road_network"]["nodes"]
             if action_plan(state["world"], state, {**vehicle, "x": n["x"], "y": n["y"]}, "spray")["can_apply"]]
    route = next(p for p in plans if p["can_apply"])
    sent = client.post(root + '/vehicles', headers=headers, json={"vehicle_id": vehicle["id"], "command": "dispatch", "target_node_id": route["target_node_id"]})
    assert sent.status_code == 200, sent.text
    arrived = tick(clock["t"] + route["planned_duration_seconds"] + 1)
    before = arrived["simulation"]["fire"]
    request = {"command_id": "spray-once-001", "kind": "vehicle.command", "arguments": {"vehicle_id": vehicle["id"], "command": "spray"}}
    begun = client.post(root + '/commands', headers=headers, json=request)
    assert begun.status_code == 200, begun.text
    assert begun.json()["commands"][0]["status"] == "executing"
    retry = client.post(root + '/commands', headers=headers, json=request).json()
    assert retry["latest_event_sequence"] == begun.json()["latest_event_sequence"]
    at = clock["t"]
    midway = tick(at + 10)
    assert midway["simulation"]["fire"]["intensity"] < before["intensity"]
    assert midway["simulation"]["fire"]["smoke_radius"] < before["smoke_radius"]
    assert midway["commands"][0]["status"] == "executing"
    finished = tick(at + 46)
    assert finished["commands"][0]["status"] == "completed"
    assert finished["simulation"]["vehicles"][0]["service"] is None
    assert len([e for e in finished["events"] if e["event_type"] == "vehicle.action_completed"]) == 1
    historical = client.get(root + f'/replay?at_seconds={at + 10}', headers=headers).json()
    assert historical["simulation"]["fire"] == midway["simulation"]["fire"]
    assert historical["simulation"]["vehicles"][0]["service"]["status"] == "executing"


def test_patient_must_be_counted_loaded_driven_and_handed_over(exercise):
    client, headers, _, root, public, code, clock, tick, start = exercise
    state = start()
    # Restore the scenario's restricted south corridor before the training route.
    for edge in state["simulation"]["road_network"]["edges"]:
        if edge["status"] != "open":
            response = client.post(root + '/roads/' + edge["id"] + '/reopen', headers=headers)
            assert response.status_code == 200, response.text
    person = next(p for p in state["simulation"]["residents"] if p["vulnerable"])
    ambulance = state["simulation"]["vehicles"][1]
    load = {"command_id": "medical-load-001", "kind": "vehicle.command", "arguments": {"vehicle_id": ambulance["id"], "command": "load", "resident_id": person["id"]}}
    assert client.post(root + '/commands', headers=headers, json=load).status_code == 409
    assert client.post(root + '/residents', headers=headers, json={"resident_ids": [person["id"]], "exit": "south", "action": "evacuate"}).status_code == 200
    arrived = tick(clock["t"] + 500)
    resident = next(p for p in arrived["simulation"]["residents"] if p["id"] == person["id"])
    assert resident["status"] == "evacuated"
    member = client.post(public + '/join?code=' + code, json={"role": "居民代表", "display_name": "清点员"}).json()
    counted = client.post(public + '/actions?code=' + code, json={"role": "居民代表", "action": "resident_counted", "message": "已核验集合点居民身份", "participant_token": member["token"], "resident_ids": [person["id"]]})
    assert counted.status_code == 200, counted.text
    load["command_id"] = "medical-load-002"
    begun = client.post(root + '/commands', headers=headers, json=load)
    assert begun.status_code == 200, begun.text
    service = begun.json()["simulation"]["vehicles"][1]["service"]
    assert service["approach_seconds"] > 0
    assert begun.json()["commands"][0]["status"] == "executing"
    at = clock["t"]
    pickup = tick(at + service["approach_seconds"] + 1)
    picked = next(p for p in pickup["simulation"]["residents"] if p["id"] == person["id"])
    assert picked["medical_transfer"]["phase"] == "loading"
    assert (picked["x"], picked["y"]) != (resident["x"], resident["y"])
    loaded = tick(at + service["duration_seconds"] + 1)
    ambulance = loaded["simulation"]["vehicles"][1]
    assert ambulance["passenger"]["id"] == person["id"]
    assert not ambulance["service_options"]["handover"]["can_apply"]
    other = next(n for n in loaded["simulation"]["road_network"]["nodes"] if n["is_exit"] and n["id"] != ambulance["passenger"]["pickup_node_id"])
    route = client.post(root + '/vehicles', headers=headers, json={"vehicle_id": ambulance["id"], "command": "dispatch", "target_node_id": other["id"]})
    assert route.status_code == 200, route.text
    remaining = route.json()["simulation"]["vehicles"][1]["remaining_seconds"]
    moved = tick(clock["t"] + remaining + 1)
    assert moved["simulation"]["vehicles"][1]["service_options"]["handover"]["can_apply"]
    handover = client.post(root + '/commands', headers=headers, json={"command_id": "handover-001", "kind": "vehicle.command", "arguments": {"vehicle_id": ambulance["id"], "command": "handover"}})
    assert handover.status_code == 200, handover.text
    assert handover.json()["commands"][0]["status"] == "executing"
    done = tick(clock["t"] + 9)
    assert done["commands"][0]["status"] == "completed"
    assert done["simulation"]["vehicles"][1]["passenger"] is None
    assert done["simulation"]["medical_transfers"][0]["phase"] == "delivered"
    assert done["simulation"]["summary"]["evacuated"] == loaded["simulation"]["summary"]["evacuated"]


def test_live_walkers_clear_reserved_corridor_before_vehicle_moves(exercise):
    client, headers, _, root, _, _, clock, tick, start = exercise
    data = start()
    assigned = client.post(root + '/residents', headers=headers, json={"resident_ids": [p["id"] for p in data["simulation"]["residents"]], "exit": "north", "action": "evacuate"})
    assert assigned.status_code == 200, assigned.text
    candidate = None
    for _ in range(12):
        state = tick(clock["t"] + 10)["simulation"]
        for vehicle in state["vehicles"]:
            for node in state["road_network"]["nodes"]:
                plan = protect_plan(plan_vehicle(state["road_network"], vehicle, node["id"]), state, vehicle["id"])
                if plan["can_apply"] and plan["hold_for_pedestrians"]:
                    candidate = (vehicle, node, plan)
                    break
            if candidate: break
        if candidate: break
    assert candidate, "Example community must expose at least one occupied vehicle corridor"
    vehicle, node, plan = candidate
    result = client.post(root + '/vehicles', headers=headers, json={"vehicle_id": vehicle["id"], "command": "dispatch", "target_node_id": node["id"]})
    assert result.status_code == 200, result.text
    initial = next(v for v in result.json()["simulation"]["vehicles"] if v["id"] == vehicle["id"])
    assert initial["state"] == "yielding"
    occupied_ids = {p["id"] for p in result.json()["simulation"]["residents"] if p.get("current_edge_id") in plan["route_edge_ids"]}
    for _ in range(25):
        current = tick(clock["t"] + 2)["simulation"]
        controlled = next(v for v in current["vehicles"] if v["id"] == vehicle["id"])
        on_roads = {p["id"] for p in current["residents"] if p.get("current_edge_id") in plan["route_edge_ids"]}
        assert on_roads.issubset(occupied_ids), "New pedestrians cannot enter a reserved corridor"
        if controlled["state"] != "yielding":
            assert controlled["state"] == "moving" and not on_roads
            break
        assert (controlled["x"], controlled["y"]) == (initial["x"], initial["y"])
    else:
        raise AssertionError("Vehicle was not released after pedestrians cleared")
