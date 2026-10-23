from copy import deepcopy
import pytest
from app.api.routes import operations
from app.models.operations import DrillSession
from app.services.fire_environment import EnvironmentTimeline
from app.services.spatial_simulation import simulate


@pytest.fixture
def kitchen(client, monkeypatch):
    token=client.post('/api/v1/auth/login',json={'username':'admin','password':'Zhiyan@2026'}).json()['access_token']
    headers={'Authorization':'Bearer '+token}
    community=client.post('/api/v1/communities/demo',headers=headers).json()
    template=next(item for item in client.get('/api/v1/scene-templates',headers=headers).json() if item['code']=='kitchen_fire')
    scene=client.post('/api/v1/communities/'+community['id']+'/scenes',headers=headers,json={'template_id':template['id'],'name':'厨房室内完整案例'}).json()
    root='/api/v1/scenes/'+scene['id']
    sources=client.get(root+'/fire-sources',headers=headers).json()
    assert sources and sources[0]['object_type']=='building'
    params={'fire_source_type':'kitchen','fire_source_object_id':sources[0]['id'],'fire_floor':2,'fire_room':'east','room_door_state':'closed',
            'start_time':'18:30','wind_direction':'微风','resident_count':8,'hydrant_status':'available','south_lane_status':'open','stair_width':1.2}
    saved=client.patch(root+'/parameters',headers=headers,json=params)
    assert saved.status_code==200,saved.text
    clock={'t':0};monkeypatch.setattr(operations,'effective_elapsed',lambda drill:clock['t'] if drill.status!='ready' else 0)
    assert client.post(root+'/publish',headers=headers).status_code==200
    response=client.post(root+'/drills',headers=headers,json={'name':'厨房运行'})
    assert response.status_code==201,response.text
    drill=response.json();base='/api/v1/drills/'+drill['id']
    def tick(at):
        clock['t']=at
        with operations.SessionLocal() as db: operations.advance_engine(db,db.get(DrillSession,drill['id']))
        result=client.get(base,headers=headers);assert result.status_code==200,result.text
        return result.json()
    return client,headers,root,params,drill,base,tick


def test_room_address_freeze_and_compartment_smoke(kitchen):
    client,headers,root,params,drill,base,tick=kitchen
    world=drill['simulation']['world']; source=world['fire_source']; model=world['indoor_environment']
    assert source['location']['kind']=='room' and source['location']['floor']==2
    assert source['position']['height']==3.38
    assert world['spatial_units']['height_mode']=='meters'
    assert len(world['tasks'])==4 and {'gas_off','containment','broadcast','escort'}=={task['kind'] for task in world['tasks']}
    assert model['source_zone_id'] in {node['id'] for node in world['spatial_network']['nodes']}
    shut=EnvironmentTimeline(world,[]).at(120)[1]['indoor']
    opened=deepcopy(world); opened['indoor_environment']['doors']=[{**door,'state':'open'} for door in model['doors']]
    flowing=EnvironmentTimeline(opened,[]).at(120)[1]['indoor']
    hall=lambda state:next(zone['smoke_density'] for zone in state['zones'] if zone['floor']==2 and zone['kind']=='corridor')
    assert hall(flowing)>hall(shut)*3
    assert next(zone['smoke_density'] for zone in flowing['zones'] if zone['floor']==1 and zone['kind']=='corridor') < hall(flowing)
    altered={**params,'fire_floor':3,'fire_room':'west'}
    assert client.patch(root+'/parameters',headers=headers,json=altered).status_code==200
    replay=client.get(base+'/replay?at_seconds=0',headers=headers)
    assert replay.json()['simulation']['world']==world
    invalid={**params,'fire_floor':21}
    assert client.post(root+'/preview',headers=headers,json=invalid).status_code==422


def test_door_command_changes_routes_and_preserves_continuous_motion(kitchen):
    client,headers,root,params,drill,base,tick=kitchen
    assert client.patch(base+'/state',headers=headers,json={'action':'start'}).status_code==200
    initial=tick(0);world=initial['simulation']['world'];source=world['indoor_environment']['source_zone_id']
    door=next(item for item in world['indoor_environment']['doors'] if item['room_id']==source)
    person=next(person for person in initial['simulation']['residents'] if person['start_zone_id']==source)
    held=tick(5);assert not next(item for item in held['simulation']['residents'] if item['id']==person['id'])['route_reachable']
    command={'command_id':'open-kitchen-room-001','kind':'indoor.door.set','arguments':{'door_id':door['id'],'state':'open'}}
    opened=client.post(base+'/commands',headers=headers,json=command)
    assert opened.status_code==200,opened.text
    assert next(item for item in opened.json()['simulation']['residents'] if item['id']==person['id'])['route_reachable']
    assigned=client.post(base+'/residents',headers=headers,json={'resident_ids':[person['id']],'exit':'north','action':'evacuate'})
    assert assigned.status_code==200,assigned.text
    assert client.post(base+'/commands',headers=headers,json=command).status_code==200
    assert len([event for event in client.get(base,headers=headers).json()['events'] if event['event_type']=='indoor.door_changed'])==1
    close={**command,'command_id':'close-occupied-room-001','arguments':{**command['arguments'],'state':'closed'}}
    assert client.post(base+'/commands',headers=headers,json=close).status_code==409
    moved=tick(9);after=next(item for item in moved['simulation']['residents'] if item['id']==person['id'])
    assert 0<abs(after['x']-person['x'])+abs(after['y']-person['y'])<3
    past=client.get(base+'/replay?at_seconds=4',headers=headers).json()['simulation']['environment']['indoor']
    assert next(item for item in past['doors'] if item['id']==door['id'])['state']=='closed'


def test_gas_task_evidence_changes_environment_and_replays(kitchen):
    client,headers,root,params,drill,base,tick=kitchen
    assert client.patch(base+'/state',headers=headers,json={'action':'start'}).status_code==200
    data=tick(40)
    if not any(event['event_type']=='robot.alarm_confirmed' for event in data['events']): data=tick(44)
    task=next(task for task in data['tasks'] if task['kind']=='gas_off')
    assert task['status']!='waiting', data['events']
    assert '2层' in task['target'] and task['target_position']['height']==3.38
    action=lambda value:client.post(base+'/tasks/'+task['id']+'/actions',headers=headers,json={'action':value,'evidence':'已关闭燃气阀并核对阀门状态'})
    assert action('accept').status_code==200
    assert action('arrive').status_code==200
    assert action('submit').status_code==409
    tick(data['elapsed_seconds']+8)
    completed=action('submit');assert completed.status_code==200,completed.text
    assert completed.json()['simulation']['environment']['gas_off'] is True
    at=completed.json()['elapsed_seconds']; state=tick(at+20)
    unchanged=EnvironmentTimeline(drill['simulation']['world'],[]).at(at+20)[0]
    assert state['simulation']['fire']['intensity']<unchanged['intensity']
    replay=client.get(base+'/replay?at_seconds='+str(at),headers=headers).json()
    assert replay['simulation']['environment']['gas_off'] is True


def test_kitchen_residents_can_complete_outdoor_assembly_and_rollcall(kitchen):
    client,headers,root,params,drill,base,tick=kitchen
    assert client.patch(base+'/state',headers=headers,json={'action':'start'}).status_code==200
    initial=tick(0)
    source=initial['simulation']['environment']['indoor']['source_zone_id']
    door=next(item for item in initial['simulation']['environment']['indoor']['doors'] if item['room_id']==source)
    opened=client.post(base+'/commands',headers=headers,json={'command_id':'full-kitchen-open-001','kind':'indoor.door.set','arguments':{'door_id':door['id'],'state':'open'}})
    assert opened.status_code==200,opened.text
    for vulnerable,action in [(False,'evacuate'),(True,'priority_assist')]:
        ids=[person['id'] for person in initial['simulation']['residents'] if person['vulnerable']==vulnerable]
        sent=client.post(base+'/residents',headers=headers,json={'resident_ids':ids,'exit':'north','action':action})
        assert sent.status_code==200,sent.text
    result=tick(240)
    assert result['simulation']['summary']['evacuated']==8
    assert all(person['assisted'] for person in result['simulation']['residents'] if person['vulnerable'])
    ids=[person['id'] for person in result['simulation']['residents']]
    counted=client.post(base+'/participant-actions',headers=headers,json={'role':'居民代表','action':'resident_counted','message':'集合区逐人核验到场','resident_ids':ids})
    assert counted.status_code==200,counted.text
    assert counted.json()['simulation']['summary']['counted']==8
    closed=client.post(base+'/commands',headers=headers,json={'command_id':'full-kitchen-close-002','kind':'indoor.door.set','arguments':{'door_id':door['id'],'state':'closed'}})
    assert closed.status_code==200,closed.text


def test_kitchen_topology_supports_people_in_another_building(kitchen):
    from app.services.spatial_world import add_spatial_layout
    world=deepcopy(kitchen[4]['simulation']['world'])
    home=next(obj for obj in world['objects'] if obj['id']==world['fire_source']['location']['object_id'])
    other=next(obj for obj in world['objects'] if obj['type']=='building' and obj['id']!=home['id'])
    world['residents'][0]['building_id']=other['id']
    rebuilt=add_spatial_layout(world,home)
    person=rebuilt['residents'][0]
    nodes={node['id']:node for node in rebuilt['spatial_network']['nodes']}
    assert nodes[person['start_node_id']]['building_id']==other['id']
    assert nodes[person['start_zone_id']]['building_id']==other['id']
    assert len({node['id'] for node in rebuilt['spatial_network']['nodes']})==len(rebuilt['spatial_network']['nodes'])


def test_new_kitchen_rooms_clear_stairs_and_use_their_own_door_portals(kitchen):
    world = kitchen[4]['simulation']['world']
    graph = world['spatial_network']
    assert graph['indoor_layout_version'] == 2
    nodes = {node['id']: node for node in graph['nodes']}
    source = world['fire_source']
    room = nodes[source['location']['node_id']]
    assert source['position'] == {key: room[key] for key in ('x', 'y', 'height')}
    for room in (node for node in nodes.values() if node['kind'] == 'room' and node['id'].startswith('indoor:')):
        outgoing = next(edge for edge in graph['edges'] if edge['start_node_id'] == room['id'])
        portal = nodes[outgoing['end_node_id']]
        assert portal['kind'] == 'corridor' and portal['x'] == room['x']
        assert portal['y'] > room['y'] + room['depth']/2
        for stair in (edge for edge in graph['edges'] if edge['kind'] == 'stairs'
                      and nodes[edge['start_node_id']]['building_id'] == room['building_id']):
            assert room['x'] - room['width']/2 > stair['start']['x'] + stair['width_meters']/2 + .08


def test_too_small_kitchen_building_is_rejected_without_mutating_the_map(kitchen):
    from app.services.indoor_layout import kitchen_rooms
    with pytest.raises(ValueError, match='住宅平面过小'):
        kitchen_rooms({'x': 10, 'y': 10, 'width': 2, 'depth': 3})
