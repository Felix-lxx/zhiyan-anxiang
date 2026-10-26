"""Deterministic compartment smoke model on the frozen pedestrian topology."""
from collections import OrderedDict
from copy import deepcopy
from app.services.indoor_layout import door_portal


def attach_indoor_environment(world):
    source = world['fire_source']; building_id = source['location']['object_id']
    building = next(obj for obj in world['objects'] if obj['id'] == building_id)
    graph = world['spatial_network']
    zones = []
    for node in graph['nodes']:
        if node.get('building_id') != building_id or node['kind'] not in {'room', 'corridor', 'stairs', 'door'}:
            continue
        width = building['width'] * (.4 if node['kind'] == 'room' else .18 if node['kind'] == 'stairs' else .7)
        depth = building['depth'] * (.4 if node['kind'] == 'room' else .7 if node['kind'] == 'stairs' else .16)
        zones.append({**node, 'width': node.get('width', width), 'depth': node.get('depth', depth)})
    ids = {zone['id'] for zone in zones}
    links, doors = [], []
    for edge in graph['edges']:
        if edge['start_node_id'] not in ids or edge['end_node_id'] not in ids:
            continue
        links.append({'id': edge['id'], 'a': edge['start_node_id'], 'b': edge['end_node_id']})
        if edge['kind'] == 'room':
            room = next(zone for zone in zones if zone['id'] == edge['start_node_id'])
            hall = next(zone for zone in zones if zone['id'] == edge['end_node_id'])
            doors.append({'id': edge['id'], 'label': room['name'] + '房门', 'room_id': room['id'], 'floor': room['floor'],
                          'portal': door_portal(room, hall, edge['width_meters']),
                          'state': world['parameters'].get('room_door_state', 'open') if room['id'] == source['location']['node_id'] else 'open'})
    world['indoor_environment'] = {'model_version': 1, 'building_id': building_id, 'source_zone_id': source['location']['node_id'],
                                 'zones': zones, 'links': links, 'doors': doors,
                                 'node_zones':{node['id']:node.get('zone_id',node['id']) for node in graph['nodes'] if node.get('building_id')==building_id}}
    for task in world['tasks']:
        if task['kind'] in {'gas_off', 'containment'}:
            task.update(target=source['name'], target_position=deepcopy(source['position']), target_node_id=source['location']['node_id'],
                        responsible_role='物业/网格员', duration_seconds=8)


class KitchenSmokeTimeline:
    def __init__(self, world, events, base_at):
        self.world, self.model, self.base_at = world, world['indoor_environment'], base_at
        self.now = 0.; self.index = 0
        self.density = {zone['id']: 0. for zone in self.model['zones']}
        self.density[self.model['source_zone_id']] = .08
        self.doors = {door['id']: door['state'] for door in self.model['doors']}
        self.changes = sorted((event for event in events if event['event_type'] == 'indoor.door_changed'), key=lambda event: (event['elapsed_seconds'], event['sequence']))
        self.frames = OrderedDict()

    def at(self, elapsed):
        elapsed = max(0., float(elapsed))
        if elapsed in self.frames: return self.frames[elapsed]
        if elapsed < self.now:
            return KitchenSmokeTimeline(self.world, self.changes, self.base_at).at(elapsed)
        while True:
            while self.index < len(self.changes) and self.changes[self.index]['elapsed_seconds'] <= self.now:
                data = self.changes[self.index]['payload']
                if data.get('door_id') in self.doors: self.doors[data['door_id']] = data['state']
                self.index += 1
            if self.now >= elapsed: break
            boundary = self.changes[self.index]['elapsed_seconds'] if self.index < len(self.changes) else elapsed
            dt = min(.5, elapsed-self.now, boundary-self.now)
            if dt <= 0: continue
            changes = {key: -value * .003 * dt for key, value in self.density.items()}
            fire, _ = self.base_at(self.now)
            changes[self.model['source_zone_id']] += .0003 * fire['intensity'] * dt
            for link in self.model['links']:
                permeability = .02 if self.doors.get(link['id']) == 'closed' else 1.
                flux = (self.density[link['a']]-self.density[link['b']]) * .08 * permeability * dt
                changes[link['a']] -= flux; changes[link['b']] += flux
            self.density = {key: max(0., min(1., value+changes[key])) for key, value in self.density.items()}
            self.now += dt
        zones = [{**zone, 'smoke_density': round(self.density[zone['id']], 4),
                  'visibility': round(100*(1-self.density[zone['id']])),
                  'temperature': round(22+self.density[zone['id']]*180, 1)} for zone in self.model['zones']]
        result = {'model_version': 1, 'building_id': self.model['building_id'], 'source_zone_id': self.model['source_zone_id'],
                  'source_label': self.world['fire_source']['name'], 'zones': zones,
                  'doors': [{**door, 'state': self.doors[door['id']]} for door in self.model['doors']]}
        result['density_by_node']={node_id:self.density.get(zone_id,0) for node_id,zone_id in self.model['node_zones'].items()}
        for key in ('equipment_layout_version', 'equipment_layouts', 'equipment_notice'):
            if key in self.model:
                result[key] = self.model[key]
        from app.services.kitchen_equipment import equipment_state
        result['devices'] = equipment_state(self.model, self.base_at(elapsed)[1].get('gas_off', False))
        self.frames[elapsed] = result
        while len(self.frames) > 128: self.frames.popitem(last=False)
        return result


def zone_density(environment, node_id=None, edge=None, progress=.5):
    zones = environment.get('indoor', {}).get('density_by_node', {})
    if edge:
        return zones.get(edge['start_node_id'], 0)*(1-progress) + zones.get(edge['end_node_id'], 0)*progress
    return zones.get(node_id, 0)
