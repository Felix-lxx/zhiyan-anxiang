"""Shared door occupancy policy for commands, agent planning and live views."""


def door_occupants(layout, door, residents, helpers):
    room = next((zone for zone in layout.get('zones', []) if zone['id'] == door['room_id']), None)
    aliases = layout.get('node_zones', {})
    blockers = []
    for kind, actors in (('resident', residents), ('helper', helpers)):
        for actor in actors:
            if actor.get('status') == 'evacuated' or actor.get('state') == 'completed':
                continue
            at_door = door['id'] in (actor.get('current_edge_id'), actor.get('edge_id'))
            in_room = aliases.get(actor.get('node_id'), actor.get('node_id')) == door['room_id']
            # Escort helpers follow an actual trail; their graph node can lag
            # behind their physical position. Check their current footprint too.
            if kind == 'helper' and room and actor.get('state') in {'approaching', 'escorting', 'blocked'}:
                in_room |= (abs(actor.get('height', -100)-room['height']) < .5
                            and abs(actor.get('x', -1000)-room['x']) <= room['width']/2
                            and abs(actor.get('y', -1000)-room['y']) <= room['depth']/2)
            if at_door or in_room:
                blockers.append({'id': actor.get('id', ''), 'kind': kind,
                                 'label': actor.get('label') or actor.get('staff_name') or ('护送员' if kind == 'helper' else '居民'),
                                 'reason': '正在通过房门' if at_door else '仍在房间内'})
    return blockers


def project_door_safety(indoor, layout, residents, helpers):
    """Never mutate the smoke timeline's cached frames with live actor data."""
    doors = []
    for door in indoor['doors']:
        occupants = door_occupants(layout, door, residents, helpers)
        doors.append({**door, 'occupants': occupants, 'can_close': not occupants,
                      'blocked_reason': '房内或门口仍有人员，请先完成疏散。' if occupants else None})
    return {**indoor, 'doors': doors}
