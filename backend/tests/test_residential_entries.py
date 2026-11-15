from copy import deepcopy
import pytest
from fastapi import HTTPException

from app.services.community_training import freeze_community
from app.services.fire_environment import EnvironmentTimeline
from app.services.household_visits import doorway
from app.services.indoor_safety import door_occupants
from test_kitchen_fire import kitchen  # noqa: F401


def test_dwelling_contract_joins_household_and_public_doorway(kitchen):
    world=deepcopy(kitchen[4]['simulation']['world'])
    world['parameters']['community_profile']='night_shift'
    freeze_community(world)
    model=world['indoor_environment']
    unit=next(u for u in model['dwellings'] if u['kitchen_zone_id']==model['source_zone_id'])
    person=next(p for p in world['residents'] if p['start_zone_id']==unit['kitchen_zone_id'])
    house=next(h for h in world['community_training']['households'] if person['id'] in h['resident_ids'])
    assert house['dwelling_id']==unit['id']
    assert house['door_id']==unit['door_id'] and house['kitchen_door_id']!=house['door_id']
    assert house['label'].endswith('1单元202户')
    assert doorway(world,person)==unit['entrance_node_id']
    nodes={n['id']:n for n in world['spatial_network']['nodes']}
    assert nodes[doorway(world,person)]['kind']=='corridor'
    assert nodes[unit['entrance_zone_id']]['kind']=='entry_hall'
    edges={e['id']:e for e in world['spatial_network']['edges']}
    assert edges[unit['kitchen_door_id']]['end_node_id']==unit['entrance_zone_id']
    assert edges[unit['door_id']]['end_node_id']==unit['entrance_node_id']
    invalid={**person,'household_entrance_node_id':unit['kitchen_zone_id']}
    with pytest.raises(HTTPException) as error:
        doorway(world,invalid)
    assert error.value.status_code==422


def test_entry_closure_protects_the_whole_dwelling_not_only_empty_vestibule(kitchen):
    client,headers,_,_,drill,root,_=kitchen
    world=drill['simulation']['world'];model=world['indoor_environment']
    unit=next(u for u in model['dwellings'] if u['kitchen_zone_id']==model['source_zone_id'])
    door=next(d for d in model['doors'] if d['id']==unit['door_id'])
    person=next(p for p in world['residents'] if p['start_zone_id']==unit['kitchen_zone_id'])
    actors=[{**person,'node_id':person['start_node_id'],'status':'waiting'}]
    assert door_occupants(model,door,actors,[])
    assert not door_occupants(model,door,[{**actors[0],'status':'evacuated'}],[])
    assert client.patch(root+'/state',headers=headers,json={'action':'start'}).status_code==200
    blocked=client.post(root+'/commands',headers=headers,json={
        'command_id':'residential-entry-closure-001','kind':'indoor.door.set',
        'arguments':{'door_id':door['id'],'state':'closed'}})
    assert blocked.status_code==409 and '人员' in blocked.text
    before=client.get(root,headers=headers).json()
    assert next(d for d in before['simulation']['environment']['indoor']['doors'] if d['id']==door['id'])['state']=='open'
    assert before['simulation']['world']==world
    projected=next(u for u in before['simulation']['environment']['indoor']['dwellings'] if u['id']==unit['id'])
    assert projected['resident_ids'] and projected['remaining']>0


def test_entry_door_controls_private_to_public_smoke_exchange(kitchen):
    world=deepcopy(kitchen[4]['simulation']['world'])
    model=world['indoor_environment']
    unit=next(u for u in model['dwellings'] if u['kitchen_zone_id']==model['source_zone_id'])
    for door in model['doors']:door['state']='open'
    open_state=EnvironmentTimeline(world,[]).at(120)[1]['indoor']
    sealed=deepcopy(world)
    next(d for d in sealed['indoor_environment']['doors'] if d['id']==unit['door_id'])['state']='closed'
    closed_state=EnvironmentTimeline(sealed,[]).at(120)[1]['indoor']
    hall=lambda state:next(z['smoke_density'] for z in state['zones'] if z['id']==unit['entrance_node_id'])
    assert hall(closed_state)<hall(open_state)
    assert next(z for z in closed_state['zones'] if z['id']==unit['entrance_zone_id'])['smoke_density']>hall(closed_state)
    assert next(d for d in model['doors'] if d['id']==unit['door_id'])['state']=='open'
