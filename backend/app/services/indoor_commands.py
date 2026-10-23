from typing import Literal
from pydantic import BaseModel, Field
from app.domain.errors import CommandRejected
from app.services.exercise_world import frozen_world


class DoorCommand(BaseModel):
    door_id: str = Field(min_length=1, max_length=255)
    state: Literal['open', 'closed']


def set_door(runtime, session, drill, arguments, identity):
    payload = DoorCommand.model_validate(arguments)
    if drill.status != 'running': raise CommandRejected(409, '请先启动演练；回放和暂停时不能改变房门。')
    world = frozen_world(session, drill)
    door = next((item for item in (world or {}).get('indoor_environment', {}).get('doors', []) if item['id'] == payload.door_id), None)
    if not door: raise CommandRejected(404, '该场次没有这扇可操作房门。')
    before = runtime.snapshot(session, drill)
    if payload.state == 'closed':
        people = before['simulation']['residents']; helpers = before['simulation'].get('helpers', [])
        room = next(zone for zone in world['indoor_environment']['zones'] if zone['id']==door['room_id'])
        escort_inside = any(helper['state']=='escorting' and abs(helper.get('height',0)-room['height'])<.5 and abs(helper['x']-room['x'])<=room['width']/2 and abs(helper['y']-room['y'])<=room['depth']/2 for helper in helpers)
        helpers = [helper for helper in helpers if helper['state'] in {'approaching','blocked'}]
        aliases=world['indoor_environment']['node_zones']
        if escort_inside or any(actor.get('edge_id') == door['id'] or actor.get('current_edge_id') == door['id'] or aliases.get(actor.get('node_id')) == door['room_id'] for actor in [*people, *helpers]):
            raise CommandRejected(409, '房内仍有人员或房门正在通行，不能关闭；请先完成疏散。')
    runtime.append_event(session, drill, 'indoor.door_changed', identity.username,
                         f"{door['label']}已{'打开' if payload.state == 'open' else '关闭'}，烟气交换与人员通行同步更新。",
                         {'door_id': door['id'], 'room_id': door['room_id'], 'state': payload.state, 'building_id': world['indoor_environment']['building_id']})
    session.flush()
    return runtime.snapshot(session, drill)
