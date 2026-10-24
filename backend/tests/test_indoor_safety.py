from copy import deepcopy

from app.services.agent_containment import occupied
from app.services.indoor_safety import door_occupants, project_door_safety


def test_door_occupancy_agrees_for_manual_agent_and_projection():
    layout = {'zones': [{'id': 'room', 'x': 10, 'y': 10, 'height': 3.38, 'width': 4, 'depth': 4}],
              'node_zones': {'start': 'room'}}
    door = {'id': 'portal', 'room_id': 'room', 'state': 'open'}
    resident = {'id': 'r1', 'label': '居民01', 'status': 'moving', 'node_id': 'hall',
                'current_edge_id': None, 'edge_id': 'portal'}
    helper = {'id': 'h1', 'state': 'escorting', 'node_id': 'hall', 'x': 10, 'y': 10, 'height': 3.38}
    indoor = {'doors': [door]}
    original = deepcopy(indoor)
    data = {'simulation': {'world': {'indoor_environment': layout}, 'residents': [resident], 'helpers': [helper]}}
    assert occupied(data, door)
    assert len(door_occupants(layout, door, [resident], [helper])) == 2
    projection = project_door_safety(indoor, layout, [resident], [helper])['doors'][0]
    assert not projection['can_close'] and projection['blocked_reason']
    assert projection['occupants'][0]['reason'] == '正在通过房门'
    assert indoor == original, 'Live occupancy must not contaminate cached historical smoke frames'
    resident.update(status='evacuated')
    helper.update(state='completed')
    assert not occupied(data, door)
    assert project_door_safety(indoor, layout, [resident], [helper])['doors'][0]['can_close']
