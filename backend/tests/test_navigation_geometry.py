from app.services.navigation_geometry import clear_segment, outdoor_connector
from app.services.spatial_world import add_spatial_layout
from app.services.vehicle_dispatch import plan_vehicle
from app.services.spatial_simulation import simulate


def test_whole_segment_and_body_clearance():
    boxes = [dict(x=0, y=0, width=4, depth=4)]
    assert not clear_segment((-5, 0), (5, 0), boxes)
    assert clear_segment((-5, 2.4), (5, 2.4), boxes)
    assert not clear_segment((-5, 2.4), (5, 2.4), boxes, .55)
    assert not clear_segment((0, 0), (0, 0), boxes)
    assert clear_segment((-5, 3), (5, 3), boxes, .55)


def test_front_door_walks_around_building_to_rear_road():
    home = dict(id="home", type="building", name="住宅楼", x=50, y=50, width=10, depth=8,
                floors=3, entry=dict(x=50, y=40))
    road = dict(id="rear", name="北侧出口", x=50, y=40, is_exit=True)
    boxes = [home]
    route, target = outdoor_connector((50, 54.3), [road], boxes)
    assert target["id"] == "rear" and len(route) >= 3
    points = [(50, 54.3), *route]
    assert all(clear_segment(a, b, boxes, .22) for a, b in zip(points, points[1:]))
    world = add_spatial_layout(dict(parameters={}, objects=[home], residents=[], road_network=dict(nodes=[road], edges=[])), home)
    graph = world["spatial_network"]
    assert any(n["id"] == "home:foyer" for n in graph["nodes"])
    for edge in graph["edges"]:
        if edge["kind"] == "outdoor":
            assert clear_segment((edge["start"]["x"], edge["start"]["y"]),
                                 (edge["end"]["x"], edge["end"]["y"]), boxes, .22)


def test_vehicle_cannot_follow_wide_road_through_building():
    network = dict(nodes=[dict(id="a", name="a", x=0, y=0), dict(id="b", name="b", x=20, y=0)],
                   edges=[dict(id="ab", start_node_id="a", end_node_id="b", status="open", width_meters=8)],
                   obstacles=[dict(x=10, y=0, width=3, depth=3)])
    vehicle = dict(x=0, y=0, minimum_width=3.5, speed=2.4)
    assert not plan_vehicle(network, vehicle, "b")["can_apply"]
    network["obstacles"][0]["y"] = 3
    assert not plan_vehicle(network, vehicle, "b")["can_apply"], "body clearance, not centerline only"
    network["obstacles"][0]["y"] = 5
    assert plan_vehicle(network, vehicle, "b")["can_apply"]


def test_legacy_crossing_is_blocked_even_after_reopen():
    from test_spatial_training import layout
    nodes = [dict(id="a", name="北门", x=30, y=40, is_exit=True), dict(id="b", name="南门", x=80, y=40, is_exit=True)]
    edge = dict(id="ab", name="穿楼道路", start_node_id="a", end_node_id="b", width_meters=4, status="open", start=nodes[0], end=nodes[1])
    world = layout(dict(nodes=nodes, edges=[edge]), 1)
    world["objects"] = [dict(id="home", type="building", x=58, y=40, width=10, depth=8)]
    world["robot_origin"] = dict(x=30, y=40)
    state = simulate(world, [dict(event_type="road.reopened", sequence=1, elapsed_seconds=0, payload=dict(blocked_edge_id="ab"))], 0)
    blocked = next(e for e in state["spatial_network"]["edges"] if e["id"] == "ab")
    assert blocked["status"] == "blocked" and blocked["geometry_blocked"]
    assert state["road_network"]["edges"][0]["status"] == "blocked"
    assert state["road_network"]["obstacles"]
