"""Read-only release checks, shared by execution and its public projection."""


def preceding_releases(step, steps, data):
    """An accepted departure can unblock a wave; arrival is a separate fact."""
    required = set(step.get('release_after', []))
    receipts = {item['id']: item['status'] for item in data.get('commands', [])}
    return [item for item in steps if item['id'] in required and
            receipts.get(item.get('command_id'), item.get('status')) not in
            {'accepted', 'executing', 'completed', 'paused'}]


def check_release(step, data, steps):
    policy = step.get('release_gate')
    if not policy or policy.get('mode') != 'shared_corridor':
        return None
    sim = data['simulation']
    people = {p['id']: p for p in sim.get('residents', [])}
    selected = [people[pid] for pid in step.get('gate_resident_ids', step.get('resident_ids', [])) if pid in people]
    selected = [p for p in selected if p['status'] != 'evacuated']
    checks = []

    def add(kind, label, passed, detail, **target):
        checks.append({'kind': kind, 'label': label, 'passed': passed, 'detail': detail, **target})

    dependencies = [s for s in steps if s['id'] in step.get('depends_on', [])]
    waiting_dependencies = [s for s in dependencies if s.get('status') != 'completed']
    add('dependencies', '前置动作', not waiting_dependencies,
        '广播、喷水等前置动作已核对完成。' if not waiting_dependencies else
        '等待：' + '、'.join(s.get('label', s['id']) for s in waiting_dependencies))
    prior = preceding_releases(step, steps, data)
    add('previous', '前批行动', not prior,
        '前批指令已受理，可并行核对本批通道。' if not prior else f'{len(prior)} 项前批行动尚未下达，不以计划文字代替执行。')
    water_problem = None
    if step.get('release_condition') == 'active_suppression':
        from app.services.agent_release import suppression_blocker
        water_problem = suppression_blocker(data, step.get('release_water_source_id'))
        add('suppression', '有效压制', not water_problem,
            water_problem or '已核对当前有效压制或火势与烟气均已消退。')
    community = sim.get('community')
    # Broadcast can solicit a receipt; it must not depend on the receipt it
    # helps obtain. Only resident departure requires confirmed notification.
    if community and step.get('kind', 'residents.assign') == 'residents.assign':
        target_ids = {p['id'] for p in selected}
        pending = [h for h in community['households'] if target_ids.intersection(h['resident_ids'])
                   and h['notification_state'] != 'confirmed']
        add('notification', '住户通知', not pending,
            f'{len(pending)} 户尚无收到回执。' if pending else '本批未到场居民均已核实收到通知。',
            resident_id=pending[0]['resident_ids'][0] if pending else None)

    spatial = {e['id']: e for e in sim.get('spatial_network', {}).get('edges', [])}
    road = {e['id']: e for e in sim.get('road_network', {}).get('edges', [])}
    blocked, reserved, congested = [], [], []
    limit = policy.get('density_limit', 55)
    for edge_id in step.get('route_edge_ids', []):
        edge = {**spatial.get(edge_id, {}), **road.get(edge_id, {})}
        target = {'edge_id': edge_id, 'name': edge.get('name', '已变更通道')}
        if not edge or edge.get('geometry_blocked') or edge.get('status') == 'blocked':
            blocked.append(target)
        elif edge.get('reserved_by_vehicle'):
            reserved.append(target)
        elif edge.get('density_percent', 0) >= limit:
            congested.append({**target, 'density': edge['density_percent'],
                              'waiting': edge.get('waiting_count', 0)})
    add('route', '通道可达', not blocked,
        f'{len(blocked)} 段原方案通道不可用，请核对并修订。' if blocked else '原方案通道没有封锁或几何冲突。',
        edge_id=blocked[0]['edge_id'] if blocked else None)
    add('traffic', '车辆管制', not reserved,
        f"{reserved[0]['name']}正由应急车辆使用，等待管制解除。" if reserved else '本批路线未被应急车辆独占。',
        edge_id=reserved[0]['edge_id'] if reserved else None)
    add('capacity', '通道负载', not congested,
        f"{congested[0]['name']}占用 {congested[0]['density']}%，{congested[0]['waiting']} 人等待；放行门槛 {limit}%。"
        if congested else f'当前路线占用低于本场 {limit}% 放行门槛。',
        edge_id=congested[0]['edge_id'] if congested else None)
    if step.get('action') == 'priority_assist':
        helped = {h['resident_id'] for h in sim.get('helpers', []) if h['state'] != 'completed'}
        needed = sum(p['id'] not in helped for p in selected)
        available = sum(s['state'] == 'available' for s in sim.get('environment', {}).get('response_staff', []))
        add('staff', '接应岗位', available >= needed,
            f'本批新需 {needed} 名，当前未执行岗位 {available} 名；计划归属仍在命令受理时核对。')
    failed = [item for item in checks if not item['passed']]
    ready_dependencies = not waiting_dependencies
    urgent = next((item for item in failed if item['kind']=='route' or
                   item['kind']=='suppression' and ready_dependencies), None)
    return {'mode': 'shared_corridor', 'at_seconds': data['elapsed_seconds'],
            'state': 'blocked' if blocked or water_problem and ready_dependencies else 'waiting' if failed else 'ready',
            'ready': not failed, 'checks': checks,
            'reason': (urgent or failed[0])['detail'] if failed else '通道条件满足，可在持续压制下放行；无须等待前批到集合点。',
            'route_count': len(step.get('route_edge_ids', [])), 'density_limit': limit}
