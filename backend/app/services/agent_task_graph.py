"""Compile and validate durable dependencies without invoking models or commands."""
from copy import deepcopy


def validate_graph(steps):
    ids = [step['id'] for step in steps]
    if len(set(ids)) != len(ids):
        raise ValueError('任务图包含重复节点。')
    known, visiting, visited = {step['id']: step for step in steps}, set(), set()

    def visit(key):
        if key not in known:
            raise ValueError('任务图引用了不存在的前置步骤。')
        if key in visiting:
            raise ValueError('任务图存在循环依赖。')
        if key in visited:
            return
        visiting.add(key)
        for dependency in known[key].get('depends_on', []):
            visit(dependency)
        visiting.remove(key)
        visited.add(key)
    for key in ids:
        visit(key)


def compile_graph(groups, at, escort_capacity=1):
    steps = deepcopy(groups)
    escort_lanes = [None] * max(1, escort_capacity)
    next_lane = 0
    for step in steps:
        step.setdefault('kind', 'residents.assign')
        step.setdefault('depends_on', [])
        if step.get('action') == 'priority_assist':
            # Split-floor groups may each need only one staff member. Reserve
            # lanes by actual group size instead of serializing every escort.
            lanes = [(next_lane + offset) % len(escort_lanes)
                     for offset in range(min(len(escort_lanes), max(1, len(step['resident_ids']))))]
            step['depends_on'] = list(dict.fromkeys([*step['depends_on'],
                *(escort_lanes[lane] for lane in lanes if escort_lanes[lane])]))
            for lane in lanes:
                escort_lanes[lane] = step['id']
            next_lane = (next_lane + len(lanes)) % len(escort_lanes)
        step.update(command_id=step.get('command_id') or 'agent-' + step['id'],
                    status='pending', reason='等待资源与前置条件校验', progress=0, last_progress_at=at)
        step['completion_rule'] = ('起火房间与门洞撤空后，由房门领域命令确认关闭' if step.get('kind') == 'indoor.door.set'
            else '消防车到达目标道路节点并恢复沿途交通' if step.get('kind') == 'vehicle.command' and step.get('arguments', {}).get('command') == 'dispatch'
            else '车辆处置事件确认有效供水与喷水已开始' if step.get('kind') == 'vehicle.command' and step.get('arguments', {}).get('command') == 'spray'
            else '机器人移动回执确认到位' if step.get('arguments', {}).get('command') == 'move'
            else '目标点广播事件确认' if step.get('kind') == 'robot.command'
            else '会合护送并到达集合点' if step.get('action') == 'priority_assist' else '居民实际到达集合点')
    validate_graph(steps)
    return steps


def _task_dependencies(task, steps):
    """Link human-verified case work to the physical action that enables it.

    These links explain ordering only.  They never turn a robot, door or
    resident receipt into proof that a responsible person completed the task.
    """
    kind = task.get('kind')
    return [step['id'] for step in steps if
            (kind == 'broadcast' and step.get('kind') == 'robot.command'
             and step.get('arguments', {}).get('command') == 'broadcast')
            or (kind == 'escort' and step.get('action') == 'priority_assist')
            or (kind == 'containment' and step.get('kind') == 'indoor.door.set')]


def _task_next_action(task):
    if task['status'] == 'completed':
        return '已完成现场动作并核验归档'
    if task['status'] == 'waiting':
        return '等待火情确认后下发责任任务'
    if task.get('verification_ready'):
        return '现场条件已满足，请提交核验证据'
    blockers = task.get('blockers', [])
    if blockers:
        return blockers[0]
    if task['status'] == 'pending':
        return '接收任务并明确现场责任人'
    if task['status'] == 'executing':
        return '到达目标位置并回执'
    return '按任务要求完成现场动作'


def case_task_view(steps, data):
    result = []
    for task in data.get('tasks', []):
        result.append({'id': task['id'], 'kind': task.get('kind'),
            'label': task.get('title', task['id']), 'state': task['status'],
            'responsible_role': task.get('responsible_role', '现场责任人'),
            'remaining_seconds': task.get('remaining_seconds'),
            'overdue': task.get('overdue', False),
            'completed_on_time': task.get('completed_on_time'),
            'blockers': task.get('blockers', []),
            'verification_ready': task.get('verification_ready', False),
            'operation_phase': (task.get('operation') or {}).get('phase'),
            'depends_on': _task_dependencies(task, steps),
            'next_required_action': _task_next_action(task),
            'completion_rule': '责任人到位、实际动作满足后提交核验证据',
            'automation': 'human_verified'})
    return result


def graph_view(steps, data, resident_ids):
    """Project automatic actions and human gates in one observable graph."""
    people = [p for p in data['simulation']['residents'] if p['id'] in set(resident_ids)]
    ready = bool(people) and all(p['status'] == 'evacuated' for p in people)
    counted = ready and all(p.get('counted') for p in people)
    tasks = case_task_view(steps, data)
    return {'version': 2, 'nodes': [
        {'id': s['id'], 'label': s['label'], 'state': s['status'], 'depends_on': s.get('depends_on', []),
         'command_id': s['command_id'], 'completion_rule': s.get('completion_rule', '领域命令回执')}
        for s in steps],
        'case_tasks': tasks,
        'human_gate': {'label': '集合到场核验', 'state': 'completed' if counted else 'ready' if ready else 'waiting',
                       'depends_on': [s['id'] for s in steps if s.get('resident_ids')],
                       'reason': '人工核验已完成' if counted else '居民已到场，请提交核验' if ready else '等待目标居民实际到场'}}


def distinct_candidates(candidates):
    result, seen = [], {}
    for candidate in candidates:
        fingerprint = tuple(sorted((p['id'], p['exit'], bool(p.get('vulnerable'))) for p in candidate['assignments']))
        fingerprint += ((candidate.get('release_policy') or {}).get('mode', 'immediate'),)
        # Same residents/routes but a different robot task is still a different action.
        fingerprint += tuple((s.get('kind'), str(sorted(s.get('arguments', {}).items())), tuple(s.get('depends_on', [])))
                             for s in candidate['groups'] if s.get('kind') in {'robot.command', 'vehicle.command', 'indoor.door.set'})
        # Candidates are decisions, not cards. If every resident, robot action
        # and dependency is identical, minor forecast jitter does not create a
        # second actionable choice.
        if fingerprint in seen:
            seen[fingerprint].setdefault('equivalent_rules', []).append(candidate['title'])
            continue
        seen[fingerprint] = candidate
        result.append(candidate)
    return result
