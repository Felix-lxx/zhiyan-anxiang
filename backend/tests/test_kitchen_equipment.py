from app.services.kitchen_equipment import attach_kitchen_equipment, clears_passages, equipment_state


def passage(x, y, height=0):
    return {'width_meters': .9, 'start': {'x': x, 'y': y, 'height': height},
            'end': {'x': x, 'y': y + 4, 'height': height}}


def test_furniture_rejects_crossing_path_but_not_another_floor():
    counter = {'x': 0, 'y': 0, 'width': 2, 'depth': .6}
    assert not clears_passages(counter, 0, [passage(0, -2)])
    assert clears_passages(counter, 0, [passage(0, -2, 3.2)])
    assert clears_passages(counter, 0, [passage(3, -2)])


def test_equipment_anchor_is_separate_from_walking_point_and_handles_no_space():
    room = {'id': 'kitchen', 'kind': 'room', 'name': '二层厨房', 'floor': 2,
            'x': 10, 'y': 10, 'height': 3.38, 'width': 4, 'depth': 4}
    world = {'indoor_environment': {'zones': [room], 'source_zone_id': room['id']},
             'fire_source': {}, 'tasks': [{'id': 'gas', 'kind': 'gas_off'}],
             'spatial_network': {'edges': [passage(10, 10, 3.38)]}}
    attach_kitchen_equipment(world)
    stove = world['indoor_environment']['equipment_layouts'][0]['stove']
    assert stove['approach_position'] == {'x': 10, 'y': 10, 'height': 3.38}
    assert world['fire_source']['ignition_position']['height'] == 4.3
    assert stove['position'] != stove['approach_position']
    valve = world['indoor_environment']['equipment_layouts'][0]['gas_valve']
    assert world['tasks'][0]['target_device_id'] == valve['id']
    assert world['tasks'][0]['device_position'] == valve['position']
    assert world['tasks'][0]['target_position'] == stove['approach_position']
    world['spatial_network']['edges'] = [passage(10, 7, 3.38)]
    world['fire_source'] = {}
    attach_kitchen_equipment(world)
    assert not world['indoor_environment']['equipment_layouts']
    assert 'ignition_position' not in world['fire_source']
    assert world['indoor_environment']['equipment_notice']


def test_valve_state_is_evidence_based_and_only_affects_source_room():
    model = {'source_zone_id': 'a', 'equipment_layouts': [
        {'room_id': room, 'gas_valve': {'id': room+':valve'}} for room in ('a', 'b')]}
    assert [item['state'] for item in equipment_state(model, False)] == ['open', 'open']
    states = equipment_state(model, True)
    assert [item['state'] for item in states] == ['closed', 'open']
    assert states[0]['basis'] == 'task_evidence'
    # A replay before the evidence does not inherit a mutated valve.
    assert equipment_state(model, False)[0]['state'] == 'open'
