from copy import deepcopy

from app.services.agent_containment import occupied
from app.services.indoor_safety import door_occupants, project_door_safety
from app.services.indoor_layout import door_portal


def test_body_at_threshold_blocks_manual_and_agent_even_after_edge_release():
    room = dict(id='room', x=10, y=10, width=4, depth=4, height=3.38)
    portal = door_portal(room, dict(x=10, y=13), .9)
    assert portal['x'] == 10 and portal['y'] == 12
    door = dict(id='door', room_id='room', portal=portal)
    layout = dict(zones=[room], node_zones={})
    resident = dict(id='r1', label='居民', status='moving', node_id='hall',
                    x=10, y=12.2, height=3.38, edge_id=None)
    data = {'simulation': {'world': {'indoor_environment': layout}, 'residents': [resident], 'helpers': []}}
    assert occupied(data, door), 'Node release does not imply the body has cleared the door'
    assert not project_door_safety({'doors': [door]}, layout, [resident], [])['doors'][0]['can_close']
    resident['y'] = 12.5
    assert not occupied(data, door)
    resident.update(y=12.2, height=6.58)
    assert not occupied(data, door), 'A person on another floor cannot block this door'
    resident.update(height=3.38, x=11)
    assert not occupied(data, door), 'A person beside the threshold is not in its passage'


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
