from copy import deepcopy

from app.services.motion_trace import record_motion, TRACE_POINTS
from app.services.spatial_simulation import simulate
from app.services.escort_motion import follow_walked_path
from test_kitchen_fire import kitchen


def test_escort_trace_keeps_a_corner_consumed_between_snapshots():
    helper = dict(x=0., y=0., height=0., escort_trail=[(0., 0., 0.), (1., 0., 0.)])
    record_motion(helper, 0)
    follow_walked_path(helper, dict(x=1., y=1., height=0.), elapsed=1)
    record_motion(helper, 1)
    assert [(point['x'], point['y']) for point in helper['motion_trace'][:2]] == [(0., 0.), (1., 0.)]
    assert helper['motion_trace'][-1]['x'] == 1.
    assert abs(helper['motion_trace'][-1]['y']-.3) < 1e-8


def test_trace_is_bounded_and_stationary_actors_do_not_emit_duplicate_points():
    actor = dict(x=0., y=0., height=0.)
    for tick in range(100):
        record_motion(actor, tick*.5)
    assert len(actor['motion_trace']) == 1
    for tick in range(100, 300):
        actor.update(x=tick/10, height=tick/100)
        record_motion(actor, tick*.5)
    assert len(actor['motion_trace']) <= TRACE_POINTS
    assert actor['motion_trace'][1]['at_seconds'] >= 149.5-4
    assert actor['motion_trace'][-1]['height'] == actor['height']


def test_live_replay_and_checkpoint_have_identical_walked_positions(kitchen):
    _, _, _, _, drill, _, _ = kitchen
    world = deepcopy(drill['simulation']['world'])
    for door in world['indoor_environment']['doors']:
        door['state'] = 'open'
    history = [dict(event_type='resident.command', elapsed_seconds=0, sequence=1,
                    payload=dict(resident_ids=[p['id'] for p in world['residents']], action='evacuate', exit='north'))]
    checkpoint = {}
    simulate(world, history, 10, checkpoint_out=checkpoint)
    live = simulate(world, history, 14, checkpoint=checkpoint)
    replay = simulate(world, history, 14)
    for a, b in zip(live['residents'], replay['residents']):
        assert a['motion_trace'] == b['motion_trace']
        assert all(a['motion_trace'][-1][key] == a[key] for key in ('x', 'y', 'height'))
        assert len(a['motion_trace']) <= TRACE_POINTS
    source_door = world['indoor_environment']['doors'][0]
    assert source_door['portal']['width'] == .9
