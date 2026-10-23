"""Safe, observable containment proposal on the same indoor navigation graph."""
def source_door(data):
    indoor = data['simulation'].get('environment', {}).get('indoor') or {}
    return next((d for d in indoor.get('doors', []) if d['room_id'] == indoor.get('source_zone_id')), None)


def occupied(data, door):
    simulation = data['simulation']
    layout = simulation.get('world', {}).get('indoor_environment', {})
    aliases = layout.get('node_zones', {})
    room = next((z for z in layout.get('zones', []) if z['id'] == door['room_id']), None)
    for actor in [*simulation['residents'], *simulation.get('helpers', [])]:
        if actor.get('status') == 'evacuated' or actor.get('state') == 'completed':
            continue
        if (aliases.get(actor.get('node_id')) == door['room_id']
                or actor.get('current_edge_id', actor.get('edge_id')) == door['id']):
            return True
        if room and actor.get('state') in {'approaching', 'escorting', 'blocked'}:
            if abs(actor.get('height', 0)-room['height']) < .5 and abs(actor['x']-room['x']) <= room['width']/2 and abs(actor['y']-room['y']) <= room['depth']/2:
                return True
    return False
