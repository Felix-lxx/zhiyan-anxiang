"""Frozen kitchen furniture and ignition anchors, separate from walking nodes."""
from copy import deepcopy


def clears_passages(counter, height, passages):
    for edge in passages:
        margin = max(.32, edge['width_meters']/2)
        bounds = ((counter['x']-counter['width']/2-margin, counter['x']+counter['width']/2+margin),
                  (counter['y']-counter['depth']/2-margin, counter['y']+counter['depth']/2+margin),
                  (height, height+2.1))
        lo, hi = 0., 1.
        for key, (minimum, maximum) in zip(('x', 'y', 'height'), bounds):
            a = edge['start'][key] + (.05 if key == 'height' else 0)
            b = edge['end'][key] + (.05 if key == 'height' else 0)
            delta = b-a
            if abs(delta) < 1e-9:
                if not minimum <= a <= maximum:
                    break
            else:
                entry, leave = sorted(((minimum-a)/delta, (maximum-a)/delta))
                lo, hi = max(lo, entry), min(hi, leave)
                if lo > hi:
                    break
        else:
            return False
    return True


def attach_kitchen_equipment(world):
    model = world['indoor_environment']
    model.pop('equipment_notice', None)
    world['fire_source'].pop('device_id', None)
    world['fire_source'].pop('ignition_position', None)
    layouts = []
    for room in model['zones']:
        if room['kind'] != 'room':
            continue
        counter = {'x': room['x'], 'y': room['y']-room['depth']*.38,
                   'width': room['width']*.82, 'depth': room['depth']*.2}
        if not clears_passages(counter, room['height'], world['spatial_network']['edges']):
            continue
        unit = counter['width']/4
        stove = {'id': room['id']+':stove', 'kind': 'stove', 'room_id': room['id'],
                 'label': room['name']+'灶台', 'floor': room['floor'],
                 'position': {'x': counter['x']+1.5*unit, 'y': counter['y'], 'height': room['height']},
                 'width': unit-.04, 'depth': counter['depth'], 'height': .92,
                 # Existing room node is the approach point, never the flame.
                 'approach_node_id': room['id'],
                 'approach_position': {key: room[key] for key in ('x', 'y', 'height')}}
        stove['ignition_position'] = {**stove['position'], 'height': round(room['height']+.92, 4)}
        valve = {'id': room['id']+':gas-valve', 'kind': 'gas_valve', 'label': room['name']+'燃气阀',
                 'room_id': room['id'], 'floor': room['floor'],
                 'position': {'x': stove['position']['x']-unit*.4, 'y': counter['y'],
                              'height': round(room['height']+1.35, 4)},
                 'approach_node_id': room['id'], 'approach_position': deepcopy(stove['approach_position'])}
        layouts.append({'room_id': room['id'], 'counter': counter, 'stove': stove, 'gas_valve': valve})
    model.update(equipment_layout_version=1, equipment_layouts=layouts)
    source = next((item['stove'] for item in layouts if item['room_id'] == model['source_zone_id']), None)
    if source:
        world['fire_source'].update(device_id=source['id'], ignition_position=deepcopy(source['ignition_position']))
    else:
        model['equipment_notice'] = '当前房间无法在通行净空之外放置灶台，保留房间火点；可在准备页增大建筑宽深。'
    source_layout = next((item for item in layouts if item['room_id'] == model['source_zone_id']), None)
    if source_layout:
        for task in world.get('tasks', []):
            if task['kind'] == 'gas_off':
                valve = source_layout['gas_valve']
                task.update(target=valve['label'], target_device_id=valve['id'],
                            target_floor=valve['floor'], device_position=deepcopy(valve['position']),
                            target_position=deepcopy(valve['approach_position']),
                            target_node_id=valve['approach_node_id'])


def equipment_state(model, gas_off):
    """Projection only: task evidence controls the source valve, not every kitchen."""
    return [{'id': item['gas_valve']['id'], 'room_id': item['room_id'],
             'state': 'closed' if gas_off and item['room_id'] == model['source_zone_id'] else 'open',
             'basis': 'task_evidence' if gas_off and item['room_id'] == model['source_zone_id'] else 'initial'}
            for item in model.get('equipment_layouts', []) if item.get('gas_valve')]
