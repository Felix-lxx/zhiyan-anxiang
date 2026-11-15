"""Human notice prerequisites share live household receipts with the simulator."""
from copy import deepcopy


def enabled(data):
    manifest = data['simulation'].get('world', {}).get('model_manifest') or {}
    return manifest.get('orchestration') == 'notice_gates_v1'


def split_departures(groups, data, routes):
    if not enabled(data):
        return groups, []
    community = data['simulation'].get('community') or {}
    pending = {
        pid: house for house in community.get('households', [])
        if house['notification_state'] != 'confirmed' for pid in house['resident_ids']
    }
    gates, ready, waiting = {}, [], []
    for group in groups:
        partitions = {}
        for pid in group['resident_ids']:
            house = pending.get(pid)
            partitions.setdefault(house['id'] if house else None, []).append(pid)
        for index, (house_id, ids) in enumerate(partitions.items()):
            part = deepcopy(group)
            part.update(
                id=group['id'] + f'-notice-{index}', resident_ids=ids,
                route_edge_ids=sorted({
                    edge_id for pid in ids
                    for edge_id in routes[group['exit']][pid].get('route_edge_ids', [])
                }),
            )
            part['label'] = group['label'].rsplit(' · ', 1)[0] + f' · {len(ids)} 人'
            if house_id:
                house = pending[ids[0]]
                gate_id = 'notice-' + house_id
                gates.setdefault(gate_id, {
                    'id': gate_id, 'kind': 'community.notice',
                    'label': '核实通知：' + house['label'], 'household_id': house_id,
                    'resident_ids': [], 'route_edge_ids': [], 'depends_on': [],
                })
                part['notification_household_id'] = house_id
                part['depends_on'] = [*part.get('depends_on', []), gate_id]
                waiting.append(part)
            else:
                ready.append(part)
    # Ready escort groups must not queue behind an unconfirmed household's lane.
    return ready + waiting, list(gates.values())


def notice_state(step, data):
    houses = (data['simulation'].get('community') or {}).get('households', [])
    house = next((house for house in houses if house['id'] == step['household_id']), None)
    if house is None:
        return {'status': 'blocked', 'progress': 0, 'reason': '本场住户身份不匹配，请重新比较计划。'}
    done = house['notification_state'] == 'confirmed'
    return {
        'status': 'completed' if done else 'waiting', 'progress': 1 if done else 0,
        'reason': '已取得本户收到回执，后续行动仍需满足通道与资源条件。' if done else
                  '等待本户收到回执；请电话或派员到户核查，不将广播覆盖当作已收到。',
    }


def departure_notified(step, data):
    house_id = step.get('notification_household_id')
    return not house_id or any(
        house['id'] == house_id and house['notification_state'] == 'confirmed'
        for house in (data['simulation'].get('community') or {}).get('households', [])
    )


def notice_summary(steps, data):
    houses = {h['id']: h for h in (data['simulation'].get('community') or {}).get('households', [])}
    gates = [step for step in steps if step.get('kind') == 'community.notice']
    pending = [step for step in gates if notice_state(step, data)['status'] != 'completed']
    return {
        'total': len(gates), 'completed': len(gates) - len(pending), 'waiting': len(pending),
        'items': [{
            'id': step['household_id'],
            'label': houses.get(step['household_id'], {}).get('label', step['label']),
            'notification_state': houses.get(step['household_id'], {}).get('notification_state', 'unknown'),
            'reason': notice_state(step, data)['reason'],
        } for step in pending[:4]],
    }
