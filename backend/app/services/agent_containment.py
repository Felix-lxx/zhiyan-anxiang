"""Safe, observable containment proposal on the same indoor navigation graph."""
from app.services.indoor_safety import door_occupants

def source_door(data):
    indoor = data['simulation'].get('environment', {}).get('indoor') or {}
    return next((d for d in indoor.get('doors', []) if d['room_id'] == indoor.get('source_zone_id')), None)


def occupied(data, door):
    simulation = data['simulation']
    layout = simulation.get('world', {}).get('indoor_environment', {})
    return bool(door_occupants(layout, door, simulation['residents'], simulation.get('helpers', [])))
