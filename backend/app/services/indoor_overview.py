"""Bounded indoor observations derived from the current authoritative snapshot."""
from math import ceil


def indoor_overview(indoor, graph, residents):
    zones = indoor.get('zones', [])
    floors = sorted({z['floor'] for z in zones if z['floor'] > 0})
    building_id = indoor['building_id']
    nodes = {n['id']: n for n in graph.get('nodes', [])}
    passages = []
    for edge in graph.get('edges', []):
        a, b = nodes.get(edge['start_node_id']), nodes.get(edge['end_node_id'])
        if not a or not b or a.get('building_id') != building_id or b.get('building_id') != building_id:
            continue
        # Per-resident room connectors duplicate the common passage and would
        # clutter a plan. The actual resident coordinates remain visible.
        if a.get('kind') == 'room_berth' or b.get('kind') == 'room_berth':
            continue
        passages.append({key: edge.get(key) for key in (
            'id', 'name', 'kind', 'start', 'end', 'width_meters', 'status',
            'geometry_blocked', 'density_percent', 'waiting_count') } | {
                'floors': sorted({a.get('floor', 0), b.get('floor', 0)}),
            })
    people = [p for p in residents if p.get('building_id') == building_id
              and p.get('indoor_stage') != 'outdoor' and p['status'] != 'evacuated']
    reports = []
    for floor in floors:
        selected = [p for p in people if max(1, ceil(p.get('current_floor') if p.get('current_floor') is not None else p.get('floor') or 1)) == floor]
        blocked = [p for p in selected if p.get('route_reachable') is False]
        unconfirmed = [p for p in selected if p.get('notification_state') in {'unnotified', 'sent'}]
        queued = [p for p in selected if p.get('waiting_for_edge')]
        candidates = [e for e in passages if floor in e['floors'] and (e.get('waiting_count') or 0) > 0]
        critical = max(candidates, key=lambda e: (e.get('waiting_count') or 0, e.get('density_percent') or 0), default=None)
        reports.append({
            'floor': floor, 'total': len(selected), 'blocked': len(blocked),
            'unconfirmed': len(unconfirmed), 'queued': len(queued),
            'needs_assistance': sum(bool(p.get('vulnerable')) and not p.get('assisted') for p in selected),
            'blocked_resident_ids': [p['id'] for p in blocked[:6]],
            'critical_passage_id': critical['id'] if critical else None,
            'reason': f'{len(blocked)} 人当前路线不可达，请先核对房门与通道。' if blocked else
                f'{len(unconfirmed)} 人所属住户尚未确认通知，先核实回执。' if unconfirmed else
                f'{len(queued)} 人等待通道，查看具体排队路段。' if queued else
                '本层仍有待疏散人员，结合烟气和接应岗位安排后续行动。' if selected else '本层当前无待疏散居民。',
        })
    return {'version': 1, 'passages': passages, 'floors': reports}


def dwelling_overview(indoor, residents, community):
    """One identity joins the floor plan, entrance, notification and members."""
    houses = {house.get('dwelling_id'): house for house in (community or {}).get('households', [])}
    doors = {door['id']: door for door in indoor['doors']}
    zones = {zone['id']: zone for zone in indoor['zones']}
    members_by_zone = {}
    for person in residents:
        members_by_zone.setdefault(person.get('start_zone_id'), []).append(person)
    result = []
    for unit in indoor.get('dwellings', []):
        house = houses.get(unit['id'])
        members = members_by_zone.get(unit['kitchen_zone_id'], [])
        result.append({**unit, 'household_id': house['id'] if house else None,
            'notification_state': house['notification_state'] if house else None,
            'resident_ids': [person['id'] for person in members],
            'remaining': sum(person['status']!='evacuated' for person in members),
            'priority': sum(bool(person.get('vulnerable')) and person['status']!='evacuated' for person in members),
            'entrance_state': doors[unit['door_id']]['state'],
            'kitchen_door_state': doors[unit['kitchen_door_id']]['state'],
            'entrance_smoke': zones[unit['entrance_zone_id']]['smoke_density']})
    return result
