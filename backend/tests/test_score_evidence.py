from copy import deepcopy
from types import SimpleNamespace

from app.services.exposure import accumulate_exposure
from app.services.scoring import score_frozen_world
from app.services.spatial_simulation import simulate
from test_drill_simulation import road_graph
from test_spatial_training import layout


def test_first_exposure_time_survives_later_accumulation():
    person = dict(smoke_exposure=4.9, vulnerable=False, node_id='corridor')
    accumulate_exposure(person, .4, .5, 30)
    first = person['smoke_exposed_at_seconds']
    assert 30 < first < 30.5
    assert person['smoke_exposure'] == 4.9 + .4 * .5 * .85
    person['node_id'] = 'stairs'
    accumulate_exposure(person, .8, 100, 30.5)
    assert person['smoke_exposed_at_seconds'] == first
    assert person['smoke_exposed_location']['node_id'] == 'corridor'


def test_result_evidence_seeks_actual_exposure_not_earlier_command(road_graph):
    world = layout(road_graph, 1)
    # The resident has received no effective broadcast, so remains indoors.
    history = [SimpleNamespace(id='early', event_type='resident.command', elapsed_seconds=1,
                               payload={'resident_ids': [], 'exit': 'north'})]
    simulation_events = [dict(vars(event), sequence=index) for index, event in enumerate(history)]
    simulation = simulate(world, simulation_events, 200)
    evidence = score_frozen_world(world, history, simulation)['details'][1]
    assert evidence['time_basis'] == 'occurrence'
    assert evidence['observed_at_seconds'] == 200
    assert evidence['related_command_at_seconds'] == 1
    assert evidence['at_seconds'] > 1
    replay = simulate(world, simulation_events, evidence['at_seconds'])
    assert replay['summary']['smoke_exposed'] == 1
    assert evidence['occurrences'][0]['resident_id'] == simulation['residents'][0]['id']
    previous = simulate(world, simulation_events, evidence['at_seconds'] - 1)
    assert previous['summary']['smoke_exposed'] == 0
    # Incremental checkpoint continuation keeps the original occurrence too.
    checkpoint = {}
    simulate(world, simulation_events, 100, checkpoint_out=checkpoint)
    continued = simulate(world, simulation_events, 200, checkpoint=deepcopy(checkpoint))
    assert continued['residents'][0]['smoke_exposed_at_seconds'] == simulation['residents'][0]['smoke_exposed_at_seconds']
