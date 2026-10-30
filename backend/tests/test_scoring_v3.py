from types import SimpleNamespace

from app.services.agent_workflow import forecast_horizon
from app.services.scoring import score_frozen_world


def event(kind, seconds, payload=None, identifier=None):
    return SimpleNamespace(
        id=identifier or f"{kind}-{seconds}", event_type=kind,
        elapsed_seconds=seconds, payload=payload or {},
    )


def completed_simulation(arrival_seconds, queue_seconds):
    residents = [
        {
            "id": f"r-{index}", "status": "evacuated", "counted": True,
            "vulnerable": index == 0, "assisted": index == 0,
            "assembly_arrived_at_seconds": arrival_seconds,
            "queue_seconds": queue_seconds, "smoke_exposure": 0,
        }
        for index in range(4)
    ]
    return {"residents": residents, "summary": {"total": 4, "evacuated": 4, "counted": 4, "smoke_exposed": 0, "missing": 0}}


def test_score_distinguishes_fast_and_congested_complete_runs():
    world = {"schema_version": 3, "parameters": {"fire_source_type": "charging_shed"}, "tasks": [{"id": "t-1", "deadline_seconds": 180}]}
    history = [
        event("robot.alarm_confirmed", 10), event("participant.acknowledge", 20),
        event("task.completed", 80, {"task_id": "t-1"}), event("resident.command", 20),
        event("participant.resident_counted", 90), event("drill.ended", 100),
    ]
    fast = score_frozen_world(world, history, completed_simulation(100, 4))
    congested = score_frozen_world(world, history, completed_simulation(170, 34))
    assert fast["version"] == 3
    assert fast["total_score"] > congested["total_score"]
    assert next(item for item in congested["details"] if item["name"] == "决策效率")["score"] < 10


def test_forecast_horizon_covers_longest_route_and_is_bounded():
    assert forecast_horizon({"north": {"r": {"route_reachable": True, "estimated_seconds": 54}}, "south": {}}) == 60
    assert forecast_horizon({"north": {"r": {"route_reachable": True, "estimated_seconds": 125}}, "south": {}}) == 90
    assert forecast_horizon({"north": {}, "south": {}}, {"can_apply": True, "duration_seconds": 42}) == 50


def test_efficiency_needs_real_arrivals_and_complete_population_for_completion_time():
    simulation = completed_simulation(50, 0)
    for person in simulation['residents']:
        person.update(status='waiting')
    simulation['summary'].update(evacuated=0, counted=0)
    empty = score_frozen_world({'tasks': []}, [], simulation)
    efficiency = next(item for item in empty['details'] if item['name'] == '决策效率')
    assert efficiency['score'] == 0
    assert empty['metrics']['completion_seconds'] is None
    simulation['residents'][0]['status'] = 'evacuated'
    simulation['summary'].update(evacuated=1, counted=1)
    partial = score_frozen_world({'tasks': []}, [], simulation)
    assert partial['metrics']['completion_seconds'] is None
    assert '疏散未完成' in next(item for item in partial['details'] if item['name'] == '决策效率')['evidence']


def test_forecast_uses_remaining_time_not_distance_already_travelled():
    routes = {'north': {'r': {'route_reachable': True, 'estimated_seconds': 120, 'remaining_seconds': 10}}}
    assert forecast_horizon(routes) == 30
    routes['north']['r']['remaining_seconds'] = 0
    assert forecast_horizon(routes) == 30


def test_new_efficiency_reference_tracks_route_length_and_escort_approach():
    from copy import deepcopy
    from app.services.scoring_reference import build_scoring_reference
    world = {'objects': [], 'robot_origin': {'x': 0, 'y': 0}, 'residents': [
        {'id': 'p', 'start_node_id': 'room', 'vulnerable': False, 'preparation_seconds': 3}],
        'spatial_network': {'nodes': [
            {'id': 'outside', 'x': 0, 'y': 0, 'kind': 'outdoor'},
            {'id': 'room', 'x': 0, 'y': 10, 'height': 10, 'kind': 'room'}],
            'edges': [{'start_node_id': 'outside', 'end_node_id': 'room', 'kind': 'stairs'}],
            'destinations': {'north': 'outside'}}}
    base = build_scoring_reference(world)
    assisted = deepcopy(world)
    assisted['residents'][0]['vulnerable'] = True
    assert build_scoring_reference(assisted)['target_seconds'] > base['target_seconds']
    longer = deepcopy(world)
    longer['spatial_network']['nodes'][1]['height'] = 30
    assert build_scoring_reference(longer)['target_seconds'] > base['target_seconds']
    simulation = completed_simulation(150, 0)
    legacy = score_frozen_world({'parameters': {}}, [], simulation)
    current = score_frozen_world({'scoring_reference': {**base, 'target_seconds': 160}}, [], simulation)
    assert legacy['metrics']['target_seconds'] == 120
    assert current['metrics']['target_seconds'] == 160
