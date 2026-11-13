"""Household visits use frozen doorway targets and the shared staff pool."""
from fastapi import HTTPException


VISIT_ACTIONS = {'household_visit', 'household_visit_cancel'}


def doorway(world, resident):
    """Stop outside the room; a visit never requires entry through its door."""
    graph = world['spatial_network']
    nodes = {node['id']: node for node in graph['nodes']}
    room = resident.get('start_zone_id', resident['start_node_id'])
    portal = nodes.get(room + ':entry')
    if portal:
        return portal['id']
    start = resident['start_node_id']
    for edge in graph['edges']:
        if start in {edge['start_node_id'], edge['end_node_id']}:
            other = edge['end_node_id'] if edge['start_node_id'] == start else edge['start_node_id']
            if nodes[other]['kind'] in {'corridor', 'door'}:
                return other
    raise HTTPException(422, '本户缺少可到达的户门通行节点，请检查场景空间。')


def prepare(session, drill, payload, member, data):
    """Return trusted event fields; callers already hold the drill command lock."""
    simulation = data['simulation']
    world = simulation['world']
    community = simulation.get('community')
    if not community:
        raise HTTPException(409, '请先在场景准备中启用社区夜班训练，再创建新场次。')
    house = next((h for h in community['households'] if h['id'] == payload.household_id), None)
    if house is None:
        raise HTTPException(422, '请选择本场冻结的住户。')
    if payload.role != '物业/网格员':
        raise HTTPException(403, '到户核查由物业或网格员执行。')
    if len(payload.message.strip()) < 6:
        raise HTTPException(422, '请填写至少六个字的核查安排或撤回原因。')
    active = next((v for v in community.get('visits', [])
                   if v['household_id'] == house['id'] and v['state'] != 'completed'), None)
    if payload.action == 'household_visit_cancel':
        if active is None:
            raise HTTPException(409, '本户没有正在执行的到户核查。')
        if not member['participant_id'].startswith('director:') and active.get('participant_id') != member['participant_id']:
            raise HTTPException(403, '只能撤回本人负责的到户核查。')
        return {'visit_id': active['id'], 'staff_id': active['staff_id']}
    if house['notification_state'] == 'confirmed':
        raise HTTPException(409, '本户已确认收到通知，无需重复派出核查。')
    if active:
        raise HTTPException(409, '本户已有值守员核查中，请查看执行进度。')
    from app.services.task_staff import select_staff
    if not any(n['kind']=='outdoor' for n in world['spatial_network']['nodes']):
        raise HTTPException(422, '场景缺少值守员室外接入点，请先完善通行图。')
    staff_id = select_staff(session, drill, data, {'responsible_role': '物业/网格员'}, member)
    resident = next(p for p in world['residents'] if p['id'] == house['resident_ids'][0])
    return {'staff_id': staff_id, 'target_node_id': doorway(world, resident),
            'resident_id': resident['id'], 'participant_id': member['participant_id'],
            'responsible': member['name']}


def check_knock(community, payload, member):
    """New worlds require actual doorway arrival before a knock receipt."""
    if not community or community['version'] < 2 or payload.channel != 'knock':
        return
    visit = next((v for v in community.get('visits', [])
                  if v['household_id'] == payload.household_id and v['state'] == 'at_door'), None)
    if visit is None:
        raise HTTPException(409, '请先派出到户核查，并等待值守员到达户门后提交敲门回执。')
    if not member['participant_id'].startswith('director:') and visit.get('participant_id') != member['participant_id']:
        raise HTTPException(403, '请由本次到户核查的责任人提交敲门回执。')
