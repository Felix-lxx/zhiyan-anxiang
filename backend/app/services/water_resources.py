"""Frozen water-source identities and connection geometry shared by all tools."""
import math

from app.services.navigation_geometry import building_obstacles, outdoor_connector


def freeze_resources(world):
    sources = [{**{key: obj[key] for key in ('id', 'name', 'x', 'y')},
                'state': 'failed' if obj.get('properties', {}).get('status') in {'failed', 'faulty'} else 'available'}
               for obj in world['objects'] if obj['type'] == 'fire_hydrant']
    primary = next((item for item in sources if '东侧' in item['name']), sources[0] if sources else None)
    if primary and world['parameters'].get('hydrant_status') in {'failed', 'faulty'}:
        primary['state'] = 'failed'
    return {'version': 1, 'primary_id': primary['id'] if primary else None, 'sources': sources}


def vehicle_obstacles(world):
    # Physical hydrant body/couplings in the existing .65-scale model. The
    # warning ring is an annotation and does not occupy the carriageway.
    return [*building_obstacles(world), *(
        {'x': item['x'], 'y': item['y'], 'width': 1.3, 'depth': .95, 'kind':'fire_hydrant'}
        for item in world['objects'] if item['type'] == 'fire_hydrant')]


def source_available(environment, source=None):
    """Old worlds retain global supply semantics; new worlds check the named source."""
    if 'hydrants' not in environment:
        return environment.get('east_hydrant') != 'failed'
    source_id = (source or {}).get('id') or environment.get('primary_hydrant_id')
    return any(item['id'] == source_id and item['state'] == 'available'
               for item in environment['hydrants'])


def effective_spray(state, vehicle, source_id=None):
    service = (vehicle or {}).get('service') or {}
    source = service.get('water_source') or {}
    return (service.get('action') == 'spray' and bool(state.get('environment', {}).get('water_suppression'))
            and source_available(state['environment'], source)
            and (not source_id or source.get('id') == source_id))


def affected_release_steps(steps, failed_source_id):
    chosen = {step.get('arguments', {}).get('water_source_id') for step in steps
              if step.get('arguments', {}).get('command') == 'spray'}
    chosen.update(step['release_water_source_id'] for step in steps if step.get('release_water_source_id'))
    if failed_source_id and chosen and None not in chosen and failed_source_id not in chosen:
        return []
    return [step for step in steps if step.get('release_condition') == 'active_suppression'
            and step['status'] != 'completed' and (not failed_source_id or
                not step.get('release_water_source_id') or step['release_water_source_id'] == failed_source_id)]


def pump_position(vehicle):
    # Matches the existing firetruck equipment inlet in local display metres.
    heading = vehicle.get('heading_radians') or 0
    return {'x': vehicle['x'] + 1.218 * math.cos(heading) + 1.8 * math.sin(heading),
            'y': vehicle['y'] - 1.218 * math.sin(heading) + 1.8 * math.cos(heading)}


def connection_options(world, state, vehicle):
    """Return real paths around frozen buildings, including hose radius clearance."""
    environment = state['environment']
    sources = environment.get('hydrants')
    if sources is None:
        # Compatibility for frozen worlds created before individual resources.
        sources = [{**{key: obj[key] for key in ('id', 'name', 'x', 'y')},
                    'state': 'failed' if environment.get('east_hydrant') == 'failed' or
                    obj.get('properties', {}).get('status') in {'failed', 'faulty'} else 'available'}
                   for obj in world.get('objects', []) if obj['type'] == 'fire_hydrant']
    options = []
    modern = bool(world.get('water_resources'))
    pump = pump_position(vehicle) if modern else {key: vehicle[key] for key in ('x', 'y')}
    obstacles = building_obstacles(world)
    for source in sources:
        item = {**source, 'can_connect': False, 'hose_points': [], 'hose_length': None}
        outlet = {'x': source['x'] + (.64025 if pump['x'] >= source['x'] else -.64025),
                  'y': source['y'], 'height': .6045} if modern else {
                      'x': source['x'], 'y': source['y'], 'height': .65}
        if source['state'] != 'available':
            item['notice'] = '水源失效，请选择其他水源或调整部署。'
        elif math.dist((outlet['x'], outlet['y']), (pump['x'], pump['y'])) > 25:
            item['notice'] = '超出 25 米供水范围，请调整车辆停靠位置。'
        else:
            route = outdoor_connector((outlet['x'], outlet['y']), [pump], obstacles, clearance=.18)
            points = [{'x': outlet['x'], 'y': outlet['y']},
                      *({'x': x, 'y': y} for x, y in route[0])] if route else []
            length = sum(math.dist((a['x'], a['y']), (b['x'], b['y']))
                         for a, b in zip(points, points[1:]))
            if not route or length > 25:
                item['notice'] = '水带绕行不可达或超过 25 米，请调整停靠位置。'
            else:
                item.update(can_connect=True, hose_points=points, hose_length=round(length, 2), connection_position=outlet,
                            notice=f'水带铺设约 {length:.1f} 米，已核对楼体净距。')
        options.append(item)
    return options
