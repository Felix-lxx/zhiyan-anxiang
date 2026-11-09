"""Supply identity, failure isolation and server-confirmed hose geometry."""
from copy import deepcopy
import math
from types import SimpleNamespace

from app.api.routes import operations
from app.models.domain import MapObject
from app.models.operations import DrillSession
from app.services.fire_environment import EnvironmentTimeline
from app.services.navigation_geometry import building_obstacles, clear_segment
from app.services.vehicle_rescue import action_plan
from app.services.water_resources import freeze_resources, pump_position
from app.services.water_resources import affected_release_steps, effective_spray
from app.services.water_resources import vehicle_obstacles
from test_exercise_world import exercise


def world_and_state():
    world = {'schema_version': 3, 'parameters': {}, 'fire_origin': {'x': 10, 'y': 6}, 'objects': [
        {'id': 'east', 'name': '东侧消火栓', 'type': 'fire_hydrant', 'x': 0, 'y': 0},
        {'id': 'north', 'name': '北侧备用消火栓', 'type': 'fire_hydrant', 'x': 0, 'y': 4},
        {'id': 'wall', 'type': 'building', 'x': 5, 'y': 0, 'width': 2, 'depth': 4},
    ]}
    world['water_resources'] = freeze_resources(world)
    fire, env = EnvironmentTimeline(world, []).at(0)
    vehicle = {'id': 'firetruck-1', 'kind': 'firetruck', 'state': 'arrived',
               'x': 9, 'y': 0, 'heading_radians': 0, 'service': None}
    return world, {'environment': env, 'fire': fire}, vehicle


def test_selected_supply_path_avoids_buildings_and_matches_real_inlet():
    world, state, vehicle = world_and_state()
    before = deepcopy((world, state, vehicle))
    plan = action_plan(world, state, vehicle, 'spray', water_source_id='east')
    assert plan['can_apply'], plan['notice']
    assert plan['water_source']['id'] == 'east'
    assert len(plan['hose_points']) > 2, 'The hose must turn around this wall'
    assert plan['hose_points'][-1] == pump_position(vehicle)
    assert plan['connection_position']['x'] > 0, 'Use the outward hydrant coupling, not its solid centre'
    for a, b in zip(plan['hose_points'], plan['hose_points'][1:]):
        assert clear_segment((a['x'], a['y']), (b['x'], b['y']), building_obstacles(world), .18)
    assert plan['hose_length'] <= 25
    assert (world, state, vehicle) == before
    assert not action_plan(world, state, vehicle, 'spray', water_source_id='foreign')['can_apply']
    for source in state['environment']['hydrants']:
        if source['id'] == 'east':
            source['state'] = 'failed'
    assert not action_plan(world, state, vehicle, 'spray', water_source_id='east')['can_apply']
    alternate = action_plan(world, state, vehicle, 'spray')
    assert alternate['can_apply'] and alternate['water_source']['id'] == 'north'


def test_failure_only_interrupts_the_source_used_by_the_action_and_replay_is_stable():
    world, _, _ = world_and_state()
    spray = {'sequence': 1, 'elapsed_seconds': 20, 'event_type': 'vehicle.action_started',
             'payload': {'action_id': 'water', 'action': 'spray', 'duration_seconds': 45,
                         'water_source': {'id': 'north'}}}
    failure = {'sequence': 2, 'elapsed_seconds': 22, 'event_type': 'inject.hydrant_failure',
               'payload': {'hydrant_id': 'east'}}
    timeline = EnvironmentTimeline(world, [spray, failure])
    assert timeline.at(30)[1]['water_suppression']
    assert timeline.at(30)[1]['east_hydrant'] == 'failed'
    assert timeline.at(30)[0]['intensity'] < timeline.at(22)[0]['intensity']
    timeline.at(30)[1]['hydrants'][0]['state'] = 'available'
    assert timeline.at(30)[1]['hydrants'][0]['state'] == 'failed', 'Readers must not mutate the event timeline'
    own_failure = {**failure, 'sequence': 3, 'elapsed_seconds': 24, 'payload': {'hydrant_id': 'north'}}
    stopped = EnvironmentTimeline(world, [spray, failure, own_failure])
    assert stopped.at(23) == timeline.at(23)
    assert not stopped.at(25)[1]['water_suppression']
    assert not timeline.at(65)[1]['water_suppression']
    del world['water_resources']
    legacy = EnvironmentTimeline(world, [spray, failure])
    assert 'hydrants' not in legacy.at(30)[1]
    assert not legacy.at(30)[1]['water_suppression'], 'Historical worlds keep their original global-failure rule'


def test_hose_range_uses_routed_length_not_straight_line_and_rotation_is_preserved():
    world, state, vehicle = world_and_state()
    world['objects'][-1].update(depth=40)
    assert not action_plan(world, state, vehicle, 'spray', water_source_id='east')['can_apply']
    vehicle['heading_radians'] = math.pi / 2
    inlet = pump_position(vehicle)
    assert abs(inlet['x'] - 10.8) < 1e-8
    assert abs(inlet['y'] + 1.218) < 1e-8


def test_vehicle_path_cannot_drive_through_a_hydrant_even_when_the_road_is_wide():
    from app.services.vehicle_dispatch import plan_vehicle
    world = {'objects':[{'id':'water', 'type':'fire_hydrant', 'x':5, 'y':0}]}
    network = {'nodes':[{'id':'a','name':'a','x':0,'y':0},{'id':'b','name':'b','x':10,'y':0}],
               'edges':[{'id':'ab','start_node_id':'a','end_node_id':'b','status':'open','width_meters':4}],
               'obstacles':[]}
    actor = {'x':0,'y':0,'kind':'firetruck','speed':2.4,'minimum_width':3.5}
    assert plan_vehicle(network, actor, 'b')['can_apply']
    network['vehicle_obstacles'] = vehicle_obstacles(world)
    assert not plan_vehicle(network, actor, 'b')['can_apply']


def test_release_monitor_checks_approved_supply_and_ignores_unrelated_failure():
    steps = [{'id':'wave', 'status':'waiting', 'release_condition':'active_suppression',
              'release_water_source_id':'north', 'resident_ids':['r1']}]
    assert affected_release_steps(steps, 'east') == []
    assert affected_release_steps(steps, 'north') == steps
    state = {'environment': {'water_suppression':True, 'hydrants':[
        {'id':'east', 'state':'failed'}, {'id':'north', 'state':'available'}]}}
    vehicle = {'service': {'action':'spray', 'water_source':{'id':'north'}}}
    assert effective_spray(state, vehicle, 'north')
    assert not effective_spray(state, vehicle, 'east')
    state['environment']['water_suppression'] = False
    assert not effective_spray(state, vehicle, 'north')


def test_water_failure_has_the_same_relevance_in_replanning_and_impact_explanation():
    from app.services.agent_impact import impact_view
    from app.services.agent_workflow import relevant_changes
    run = SimpleNamespace(scope={'resident_ids':['r1'], 'robot_broadcast':False},
        candidates=[], selected_candidate=None, evidence=[], observed_sequence=0, drill_session_id='d',
        steps=[{'id':'wave', 'label':'北侧供水后放行', 'status':'waiting', 'release_condition':'active_suppression',
                'release_water_source_id':'north', 'resident_ids':['r1']}])
    event = SimpleNamespace(id='water-failure', sequence=1, elapsed_seconds=20,
        event_type='inject.hydrant_failure', message='北侧供水失效', payload={'hydrant_id':'east', 'target':'东侧消火栓'})

    class Session:
        def scalars(self, statement):
            sql = str(statement.compile(compile_kwargs={'literal_binds':True}))
            return [] if 'command.accepted' in sql else [event]

    data = {'latest_event_sequence':1, 'elapsed_seconds':20,
            'simulation':{'residents':[{'id':'r1', 'status':'waiting', 'label':'居民1', 'route_reachable':True}]}}
    assert relevant_changes(Session(), run, 0, data) == []
    assert impact_view(Session(), run, data)['changes_count'] == 0
    event.payload = {'hydrant_id':'north', 'target':'北侧备用消火栓'}
    assert relevant_changes(Session(), run, 0, data)[0][0] == 'needs_review'
    impact = impact_view(Session(), run, data)
    assert impact['affected_count'] == 1 and impact['step_count'] == 1
    assert impact['changes'][0]['resource_id'] == 'north'
    assert '水源失效' in impact['residents'][0]['reason']


def test_real_backup_supply_survives_other_source_failure_and_stops_on_own_failure(exercise):
    client, headers, demo, old_root, _, _, clock, _, _ = exercise
    original = client.get(old_root, headers=headers).json()['simulation']['world']
    sources = original['water_resources']['sources']
    east = next(item for item in sources if '东侧' in item['name'])
    north = next(item for item in sources if '备用' in item['name'])
    # Edit preparation data, then freeze a new run. The first world stays intact.
    with operations.SessionLocal() as db:
        db.get(MapObject, north['id']).geometry = {'x': east['x'], 'y': east['y'] + 2}
        db.commit()
    created = client.post('/api/v1/scenes/' + demo['scene_id'] + '/drills', headers=headers,
                          json={'name': '备用供水接口回归'})
    assert created.status_code == 201, created.text
    root = '/api/v1/drills/' + created.json()['id']
    drill_id = created.json()['id']
    assert client.get(old_root, headers=headers).json()['simulation']['world'] == original

    def tick(at):
        clock['t'] = at
        with operations.SessionLocal() as db:
            operations.advance_engine(db, db.get(DrillSession, drill_id))
        return client.get(root, headers=headers).json()

    assert client.patch(root + '/state', headers=headers, json={'action': 'start'}).status_code == 200
    data = tick(0)
    from app.services.agent_resources import vehicle_suppression_support
    support, _ = vehicle_suppression_support(data)
    assert support['can_apply'], support['notice']
    if support['target_node_id']:
        sent = client.post(root + '/vehicles', headers=headers, json={
            'vehicle_id': 'firetruck-1', 'command': 'dispatch', 'target_node_id': support['target_node_id']})
        assert sent.status_code == 200, sent.text
        data = tick(support['duration_seconds'] + 1)
    request = {'vehicle_id': 'firetruck-1', 'command': 'spray', 'water_source_id': north['id']}
    preview = client.post(root + '/vehicles/preview', headers=headers, json=request)
    assert preview.status_code == 200 and preview.json()['can_apply'], preview.text
    assert preview.json()['route_points'] == preview.json()['hose_points']
    invalid = client.post(root + '/vehicles', headers=headers, json={**request, 'water_source_id': 'other-world'})
    assert invalid.status_code == 409
    begun = client.post(root + '/commands', headers=headers, json={
        'command_id': 'named-backup-water-001', 'kind': 'vehicle.command', 'arguments': request})
    assert begun.status_code == 200, begun.text
    service = begun.json()['simulation']['vehicles'][0]['service']
    assert service['water_source']['id'] == north['id'] and service['hose_points']
    failed = client.post(root + '/inject', headers=headers, json={'event_type': 'hydrant_failure', 'hydrant_id': east['id']})
    assert failed.status_code == 200, failed.text
    assert failed.json()['simulation']['environment']['water_suppression']
    assert failed.json()['simulation']['vehicles'][0]['service']['water_source']['id'] == north['id']
    reply = client.post(root + '/assistant/chat', headers=headers, json={'message':'现在使用哪个水源？', 'use_model':False})
    assert reply.status_code == 200, reply.text
    assert any(item['id']=='S10' and '东侧消火栓：失效' in item['detail'] and '北侧备用消火栓：可用' in item['detail']
               for item in reply.json()['sources'])
    assert '正在使用北侧备用消火栓' in reply.json()['answer']
    at = clock['t']
    midway = tick(at + 3)
    assert midway['simulation']['fire']['intensity'] < failed.json()['simulation']['fire']['intensity']
    stopped = client.post(root + '/inject', headers=headers, json={'event_type': 'hydrant_failure', 'hydrant_id': north['id']})
    assert stopped.status_code == 200, stopped.text
    assert not stopped.json()['simulation']['environment']['water_suppression']
    assert stopped.json()['simulation']['vehicles'][0]['service'] is None
    assert client.post(root + '/vehicles', headers=headers, json=request).status_code == 409
    assert client.post(root + '/inject', headers=headers, json={'event_type': 'hydrant_failure', 'hydrant_id': 'other-world'}).status_code == 422
    historical = client.get(root + f'/replay?at_seconds={at}', headers=headers)
    assert historical.status_code == 200 and historical.json()['simulation']['environment']['water_suppression']
    past_chat = client.post(root + '/assistant/chat', headers=headers, json={'message':'水源情况', 'use_model':False, 'at_seconds':0})
    assert past_chat.status_code == 200 and '历史回放' in past_chat.json()['answer']
    assert all(item['kind']=='branch' for item in past_chat.json()['actions'])
