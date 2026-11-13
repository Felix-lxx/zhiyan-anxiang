"""Shared physical staff occupancy for human task receipts and escorts."""
from fastapi import HTTPException


def occupations(events):
    active = {}
    for event in events:
        kind = event['event_type'] if isinstance(event, dict) else event.event_type
        data = event['payload'] if isinstance(event, dict) else event.payload
        if kind == 'task.accepted' and data.get('staff_id'):
            active[data['task_id']] = data
        elif kind in {'task.completed', 'task.released'}:
            active.pop(data.get('task_id'), None)
    return active


def select_staff(session, drill, data, task, member):
    if not data['simulation']['world'].get('community_training') or task['responsible_role'] != '物业/网格员':
        return None
    from app.services.agent_claims import claims_for
    claimed = {c.resource_key.removeprefix('staff:') for c in claims_for(session, drill.id)
               if c.run_id and c.resource_key.startswith('staff:')}
    staff = data['simulation']['environment'].get('response_staff', [])
    if not member['participant_id'].startswith('director:') and any(
            s.get('task_participant_id') == member['participant_id'] for s in staff):
        raise HTTPException(409, '你已有未结束的现场任务，请完成或撤回后再接收。')
    available = [s for s in staff if s['state']=='available' and s['id'] not in claimed
                 and (not s.get('participant_id') or s['participant_id']==member['participant_id'])]
    if not available:
        raise HTTPException(409, '值守岗位均已执行或归属护送计划，请完成、撤回任务或调整计划后再接收。')
    return available[0]['id']
