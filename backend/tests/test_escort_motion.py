import math
from types import SimpleNamespace
from test_drill_simulation import road_graph, event
from test_spatial_training import layout
from app.services.escort_motion import can_meet, follow_walked_path
from app.services.spatial_simulation import simulate, xyz
from app.services.command_feedback import command_feedback


def test_contact_requires_connected_space_and_trailing_follows_corner():
    helper=dict(x=0,y=0,height=0,node_id='room-a',edge_id=None)
    resident=dict(x=.3,y=0,height=0,node_id='room-b',edge_id=None)
    assert not can_meet(helper,resident,{})
    resident['node_id']='room-a'
    assert can_meet(helper,resident,{})
    for x,y in [(0,0),(0,1),(0,2),(1,2),(2,2)]:
        resident.update(x=x,y=y)
        follow_walked_path(helper,resident)
    assert math.isclose(helper['x'],1.3) and helper['y']==2
    assert len(helper['escort_trail'])<=3


def test_mid_segment_assistance_and_blocking_do_not_freeze_target(road_graph):
    world=layout(road_graph,1)
    history=[event('robot.broadcast_completed',0,{})]
    before=simulate(world,history,45)['residents'][0]
    assert before['edge_id']
    history += [event('resident.command',45,{'resident_ids':['resident-1'],'exit':'north','action':'priority_assist'},2),
                event('inject.channel_blocked',45,{'blocked_edge_id':before['edge_id']},3)]
    after=simulate(world,history,46)['residents'][0]
    assert after['edge_progress']<before['edge_progress'] or after['edge_id'] is None
    assert 0<math.dist(xyz(before),xyz(after))<=1.31


def test_helper_blockage_overrides_resident_eta():
    event=SimpleNamespace(sequence=1,elapsed_seconds=0,actor='导演',message='护送',event_type='command.accepted',
        payload={'command_id':'assist','kind':'residents.assign','arguments':{'resident_ids':['r1'],'action':'priority_assist'},'event_ids':[]})
    sim={'residents':[dict(id='r1',label='居民1',status='waiting',route_reachable=True,remaining_seconds=20)],
         'helpers':[dict(resident_id='r1',state='blocked',route_reachable=False,responsible='护送员',behavior='会合通道被封锁')]}
    receipt=command_feedback([event],sim,None,10,'running')[0]
    assert receipt['status']=='blocked' and receipt['remaining_seconds'] is None
    assert '会合通道被封锁' in receipt['reason']
