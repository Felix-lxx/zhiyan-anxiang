from copy import deepcopy

from app.services.indoor_overview import indoor_overview
from test_kitchen_fire import kitchen  # noqa: F401


def test_floor_report_uses_current_floor_and_keeps_distinct_waiting_reasons():
    indoor={'building_id':'home','zones':[{'id':'room','floor':2},{'id':'hall','floor':1}]}
    people=[{'id':'a','building_id':'home','floor':4,'current_floor':1.4,'status':'moving',
             'route_reachable':False,'notification_state':'sent','vulnerable':True,'waiting_for_edge':'stairs'},
            {'id':'b','building_id':'home','floor':2,'status':'evacuated'},
            {'id':'c','building_id':'other','floor':2,'status':'waiting'}]
    graph={'nodes':[{'id':n,'building_id':'home','floor':floor} for n,floor in [('a',2),('b',1)]],
           'edges':[{'id':'stairs','name':'楼梯','kind':'stairs','start_node_id':'a','end_node_id':'b',
                     'start':{'x':1,'y':1,'height':3.38},'end':{'x':1,'y':2,'height':.18},
                     'width_meters':1.2,'status':'open','waiting_count':1,'density_percent':70}]}
    original=deepcopy((indoor,graph,people))
    view=indoor_overview(indoor,graph,people)
    floor=next(f for f in view['floors'] if f['floor']==2)
    assert floor['total']==floor['blocked']==floor['queued']==floor['unconfirmed']==floor['needs_assistance']==1
    assert floor['critical_passage_id']=='stairs' and floor['blocked_resident_ids']==['a']
    assert len(view['passages'])==1
    assert (indoor,graph,people)==original
    people[0].update(current_floor=1,status='evacuated')
    assert all(f['total']==0 for f in indoor_overview(indoor,graph,people)['floors'])


def test_private_berths_and_foreign_connections_do_not_duplicate_floor_passages():
    indoor={'building_id':'home','zones':[{'id':'room','floor':1}]}
    graph={'nodes':[{'id':'private','kind':'room_berth','building_id':'home','floor':1},
                    {'id':'room','kind':'room','building_id':'home','floor':1},
                    {'id':'foreign','kind':'room','building_id':'other','floor':1}],
           'edges':[{'id':'private-path','start_node_id':'private','end_node_id':'room'},
                    {'id':'foreign-path','start_node_id':'room','end_node_id':'foreign'}]}
    assert indoor_overview(indoor,graph,[])['passages']==[]


def test_real_door_change_updates_plan_passage_and_replay_preserves_closed_door(kitchen):
    client,headers,_,_,drill,base,tick=kitchen
    assert client.patch(base+'/state',headers=headers,json={'action':'start'}).status_code==200
    before=tick(3)
    indoor=before['simulation']['environment']['indoor']
    door=next(d for d in indoor['doors'] if d['room_id']==indoor['source_zone_id'])
    passage=lambda state:next(e for e in state['navigation']['passages'] if e['id']==door['id'])
    assert passage(indoor)['status']=='blocked'
    opened=client.post(base+'/commands',headers=headers,json={'command_id':'indoor-overview-open-001',
        'kind':'indoor.door.set','arguments':{'door_id':door['id'],'state':'open'}})
    assert opened.status_code==200, opened.text
    assert passage(opened.json()['simulation']['environment']['indoor'])['status']=='open'
    past=client.get(base+'/replay?at_seconds=2',headers=headers)
    assert past.status_code==200, past.text
    assert passage(past.json()['simulation']['environment']['indoor'])['status']=='blocked'
    assert drill['simulation']['world']['indoor_environment']['equipment_layout_version']==3
