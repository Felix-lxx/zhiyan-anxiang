"""Deterministic building release waves shared by planning and execution."""
from copy import deepcopy
from app.services.water_resources import source_available


def staged_release(groups, population, resource_steps, spray_id, water_source_id=None):
    """Each building waits for the previous building's actual assembly arrival.

    One building is one wave: a building-wide broadcast must not release half
    a nominal batch early. Escort capacity is still enforced by compile_graph.
    """
    waves = {}
    for group in groups:
        for resident_id in group['resident_ids']:
            building_id = population[resident_id].get('building_id') or 'outdoor'
            waves.setdefault(building_id, []).append((group, resident_id))
    result, robot = [], deepcopy(resource_steps)
    # Use the same building order as the robot route/battery preview. Changing
    # that order would invalidate the planned segments and arrival estimates.
    order = [step.get('building_id') for step in robot if step.get('arguments', {}).get('command') == 'move']
    waves = {key: waves[key] for key in dict.fromkeys([*order, *waves]) if key in waves}
    previous = []
    for wave_index, (building_id, members) in enumerate(waves.items()):
        wave_spray_id = spray_id
        if wave_index:
            wave_spray_id = f"{members[0][0]['id']}-suppression-{wave_index + 1}"
            robot.append({'id': wave_spray_id, 'label': f'第 {wave_index + 1} 批放行前核对并接续喷水',
                'kind': 'vehicle.command', 'arguments': {'command':'spray','vehicle_id':'firetruck-1',
                    **({'water_source_id': water_source_id} if water_source_id else {})},
                'depends_on': list(previous), 'resident_ids': [], 'route_edge_ids': []})
        wave_groups = {}
        for group, resident_id in members:
            key = group['id']
            if key not in wave_groups:
                copy = deepcopy(group)
                copy.update(id=f"{key}-wave-{wave_index + 1}", resident_ids=[],
                            release_wave=wave_index + 1, building_id=building_id,
                            release_condition='active_suppression',
                            release_water_source_id=water_source_id,
                            depends_on=[*previous, *([wave_spray_id] if wave_spray_id else [])])
                wave_groups[key] = copy
            wave_groups[key]['resident_ids'].append(resident_id)
        broadcast = next((step for step in robot if step.get('building_id') == building_id
                          and step.get('arguments', {}).get('command') == 'broadcast'), None)
        for step in robot:
            if step.get('building_id') == building_id and step.get('arguments', {}).get('command') == 'move':
                step['depends_on'] = list(dict.fromkeys([*previous,
                                                       *([wave_spray_id] if wave_spray_id else [])]))
        for group in wave_groups.values():
            group['label'] = f"第 {wave_index + 1} 批 · {group['label'].rsplit(' · ', 1)[0]} · {len(group['resident_ids'])} 人"
            if broadcast:
                group['depends_on'].append(broadcast['id'])
            result.append(group)
        previous = [group['id'] for group in wave_groups.values()]
    return result, robot


def hazard_cleared(data):
    fire = data['simulation'].get('fire', {})
    return fire.get('intensity', float('inf')) <= 0 and fire.get('smoke_radius', float('inf')) <= 0


def suppression_blocker(data, water_source_id=None):
    if hazard_cleared(data):
        return None
    environment = data['simulation'].get('environment', {})
    vehicle = next((item for item in data['simulation'].get('vehicles', [])
                    if item.get('id') == 'firetruck-1'), {})
    if not source_available(environment, (vehicle.get('service') or {}).get('water_source')):
        return '供水不可用，暂停后续放行，请选择备用水源并重新比较撤离方案。'
    if (vehicle.get('service') or {}).get('action') != 'spray':
        return '当前未持续有效喷水，暂停后续放行，请检查消防车或调整方案。'
    active_source = (vehicle['service'].get('water_source') or {}).get('id')
    if water_source_id and active_source != water_source_id:
        return '当前供水与已批准方案不一致，请重新比较并确认水源后放行。'
    if not environment.get('water_suppression'):
        return '供水或喷水作用尚未生效，暂停后续放行，请核对水源与处置回执。'
    return None
