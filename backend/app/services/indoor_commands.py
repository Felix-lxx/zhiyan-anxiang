from typing import Literal
from pydantic import BaseModel, Field
from app.domain.errors import CommandRejected
from app.services.exercise_world import frozen_world
from app.services.indoor_safety import door_occupants


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
    current = next(item for item in before['simulation']['environment']['indoor']['doors'] if item['id'] == door['id'])
    if current['state'] == payload.state:
        return before
    if payload.state == 'closed':
        simulation = before['simulation']
        if door_occupants(world['indoor_environment'], door, simulation['residents'], simulation.get('helpers', [])):
            raise CommandRejected(409, '房内仍有人员或房门正在通行，不能关闭；请先完成疏散。')
    runtime.append_event(session, drill, 'indoor.door_changed', identity.username,
                         f"{door['label']}已{'打开' if payload.state == 'open' else '关闭'}，烟气交换与人员通行同步更新。",
                         {'door_id': door['id'], 'room_id': door['room_id'], 'state': payload.state, 'building_id': world['indoor_environment']['building_id']})
    session.flush()
    return runtime.snapshot(session, drill)
