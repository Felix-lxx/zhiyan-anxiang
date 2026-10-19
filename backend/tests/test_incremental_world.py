from copy import deepcopy
import json
from time import perf_counter

from test_drill_simulation import road_graph, event
from test_spatial_training import layout
from test_exercise_world import exercise
from app.services.spatial_simulation import simulate
from app.services.spatial_world import add_spatial_layout


def test_checkpoint_roundtrip_same_tick_commands_rewind_and_invalid_history(road_graph):
    world = layout(road_graph, 8)
    events = [event("robot.broadcast_completed", 0, {})]
    saved = {}
    first = simulate(world, events, 30, checkpoint_out=saved)
    checkpoint = json.loads(json.dumps(saved))
    assert simulate(world, events, 30, checkpoint=checkpoint) == first
    eid = first["residents"][0]["edge_id"]
    events += [event("inject.channel_blocked", 30, {"blocked_edge_id": eid}, 2),
               event("road.reopened", 35, {"blocked_edge_id": eid}, 3)]
    assert simulate(world, events, 40, checkpoint=checkpoint) == simulate(world, events, 40)
    assert simulate(world, events, 12, checkpoint=checkpoint) == simulate(world, events, 12)
    retroactive = [event("robot.broadcast_completed", 5, {})]
    assert simulate(world, retroactive, 40, checkpoint=checkpoint) == simulate(world, retroactive, 40)
    changed = deepcopy(world)
    changed["parameters"]["hydrant_status"] = "failed"
    assert simulate(changed, events, 40, checkpoint=checkpoint) == simulate(changed, events, 40)


def test_checkpoint_preserves_helper_and_queue_state(road_graph):
    world = layout(road_graph, 12)
    events = [event("robot.broadcast_completed", 0, {}), event("resident.command", 0,
        {"resident_ids": ["resident-3"], "exit": "north", "action": "priority_assist"}, 2)]
    saved = {}
    simulate(world, events, 45, checkpoint_out=saved)
    assert simulate(world, events, 75, checkpoint=saved) == simulate(world, events, 75)


def test_two_buildings_have_independent_stairs_and_complete_arrival(road_graph):
    world = layout(road_graph, 4)
    a = dict(id="home", name="甲楼", type="building", x=58, y=40, width=10, depth=8, floors=3, entry={"x":58,"y":48})
    b = dict(a, id="second", name="乙楼", x=34, y=60, floors=2, entry={"x":34,"y":48}, properties={"stair_width":2.4})
    world["objects"] = [a, b]
    for p in world["residents"][2:]: p.update(building_id="second", floor=2)
    add_spatial_layout(world, a)
    nodes = {n["id"]: n for n in world["spatial_network"]["nodes"]}
    for p in world["residents"]: assert nodes[p["start_node_id"]]["building_id"] == p["building_id"]
    assert any(e["kind"] == "stairs" and e["width_meters"] == 2.4 for e in world["spatial_network"]["edges"])
    final = simulate(world, [event("robot.broadcast_completed", 0, {})], 250)
    assert final["summary"]["evacuated"] == 4
    assert all(p["building_exited_at_seconds"] < p["assembly_arrived_at_seconds"] for p in final["residents"])


def test_warm_tick_is_equivalent_without_replaying_long_history(road_graph):
    world = layout(road_graph, 100)
    events = [event("robot.broadcast_completed", 0, {})]
    checkpoint = {}
    start = perf_counter()
    simulate(world, events, 180, checkpoint_out=checkpoint)
    cold = perf_counter()-start
    start = perf_counter()
    warm = simulate(world, events, 181, checkpoint=checkpoint)
    warm_time = perf_counter()-start
    assert warm == simulate(world, events, 181)
    print(f"100 residents: cold 180s={cold:.4f}s; warm +1s={warm_time:.4f}s")


def test_engine_checkpoint_is_durable_but_not_exposed_to_clients(exercise):
    from sqlalchemy import select
    from app.api.routes import operations
    from app.models.operations import DrillStateSnapshot
    from app.services import simulation_checkpoints as cache
    from app.services.state_store import load_snapshot, restore_engine_checkpoint
    client, headers, demo, root, _, _, _, tick, _ = exercise
    assert client.patch(root+'/state', headers=headers, json={"action":"start"}).status_code == 200
    state = tick(6)
    world = state['simulation']['world']
    assert '_engine_checkpoint' not in state
    with operations.SessionLocal() as session:
        record = session.scalar(select(DrillStateSnapshot).where(DrillStateSnapshot.drill_session_id==demo['drill_id']).order_by(DrillStateSnapshot.elapsed_seconds.desc()))
        assert record.payload['_engine_checkpoint']['now'] == 6
        assert record.payload['simulation']['world'] is None
        assert record.payload['_frozen_world_ref'] is True
        assert load_snapshot(session, demo['drill_id'])['simulation']['world'] == world
        assert '_engine_checkpoint' not in load_snapshot(session, demo['drill_id'])
        with cache._lock: cache._states.clear()
        assert cache.recall(world, 6) is None
        restore_engine_checkpoint(session, demo['drill_id'], world, 6)
        assert cache.recall(world, 6)['people'] == record.payload['_engine_checkpoint']['people']


def test_large_assembly_berths_remain_inside_community(road_graph):
    world = layout(road_graph, 1000)
    slots = [n for n in world['spatial_network']['nodes'] if n['kind']=='assembly']
    assert all(0 <= n['x'] <= 100 and 0 <= n['y'] <= 100 for n in slots)
    assert len(world['spatial_network']['berths']['north']) == 1000


def test_forecast_does_not_evict_live_checkpoint(road_graph):
    from app.services.simulation_checkpoints import remember, recall
    world = layout(road_graph, 3)
    history = [event("robot.broadcast_completed", 0, {})]
    current, forecast = {}, {}
    simulate(world, history, 10, checkpoint_out=current)
    simulate(world, history, 40, checkpoint=current, checkpoint_out=forecast)
    remember(world, current)
    remember(world, forecast)
    assert recall(world, 11)["now"] == 10
    assert recall(world, 41)["now"] == 40


def test_staff_slot_reused_at_last_position_instead_of_spawn(road_graph):
    from app.services.spatial_simulation import xyz
    world = layout(road_graph, 3)
    world['response_staff'] = [{"id":"duty-one", "name":"值守一号", "role":"物业/网格员", "source":"simulation", "available":True, "origin":world["robot_origin"]}]
    history = [event("resident.command", 0, {"resident_ids":["resident-3"], "exit":"north", "action":"priority_assist"})]
    first = simulate(world, history, 300)
    assert first["helpers"][0]["state"] == "completed"
    history.append(event("resident.command", 300, {"resident_ids":["resident-2"], "exit":"north", "action":"priority_assist"}, 2))
    second = simulate(world, history, 300)
    helper = next(h for h in second["helpers"] if h["resident_id"] == "resident-2")
    assert helper["staff_id"] == "duty-one"
    assert xyz(helper) == xyz(next(p for p in first["residents"] if p["id"] == "resident-3"))
    assert sum(h["state"] != "completed" for h in second["helpers"]) == 1
