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


def compile_graph(groups, at):
    steps, previous_escort = deepcopy(groups), None
    for step in steps:
        step.setdefault('kind', 'residents.assign')
        step.setdefault('depends_on', [])
        if step.get('action') == 'priority_assist':
            if previous_escort:
                step['depends_on'] = list(dict.fromkeys([*step['depends_on'], previous_escort]))
            previous_escort = step['id']
        step.update(command_id=step.get('command_id') or 'agent-' + step['id'],
                    status='pending', reason='等待资源与前置条件校验', progress=0, last_progress_at=at)
        step['completion_rule'] = ('起火房间与门洞撤空后，由房门领域命令确认关闭' if step.get('kind') == 'indoor.door.set' else '机器人移动回执确认到位' if step.get('arguments', {}).get('command') == 'move'
            else '目标点广播事件确认' if step.get('kind') == 'robot.command'
            else '会合护送并到达集合点' if step.get('action') == 'priority_assist' else '居民实际到达集合点')
    validate_graph(steps)
    return steps


def graph_view(steps, data, resident_ids):
    """The human gate is observable, never a synthetic task completion command."""
    people = [p for p in data['simulation']['residents'] if p['id'] in set(resident_ids)]
    ready = bool(people) and all(p['status'] == 'evacuated' for p in people)
    counted = ready and all(p.get('counted') for p in people)
    return {'version': 1, 'nodes': [
        {'id': s['id'], 'label': s['label'], 'state': s['status'], 'depends_on': s.get('depends_on', []),
         'command_id': s['command_id'], 'completion_rule': s.get('completion_rule', '领域命令回执')}
        for s in steps],
        'case_tasks': [{'id': task['id'], 'label': task['title'], 'state': task['status'],
            'responsible_role': task['responsible_role'], 'remaining_seconds': task.get('remaining_seconds'),
            'overdue': task.get('overdue', False), 'blockers': task.get('blockers', []),
            'verification_ready': task.get('verification_ready', False),
            'depends_on': [s['id'] for s in steps if (task['kind'] == 'broadcast' and s.get('kind') == 'robot.command')
                or (task['kind'] == 'escort' and s.get('action') == 'priority_assist')],
            'completion_rule': '责任人到位、实际动作满足后提交核验证据'} for task in data.get('tasks', [])],
        'human_gate': {'label': '集合到场核验', 'state': 'completed' if counted else 'ready' if ready else 'waiting',
                       'reason': '人工核验已完成' if counted else '居民已到场，请提交核验' if ready else '等待目标居民实际到场'}}


def distinct_candidates(candidates):
    result, seen = [], {}
    for candidate in candidates:
        fingerprint = tuple(sorted((p['id'], p['exit'], bool(p.get('vulnerable'))) for p in candidate['assignments']))
        # Same residents/routes but a different robot task is still a different action.
        fingerprint += tuple((s.get('kind'), str(sorted(s.get('arguments', {}).items())))
                             for s in candidate['groups'] if s.get('kind') in {'robot.command', 'indoor.door.set'})
        # Candidates are decisions, not cards. If every resident, robot action
        # and dependency is identical, minor forecast jitter does not create a
        # second actionable choice.
        if fingerprint in seen:
            seen[fingerprint].setdefault('equivalent_rules', []).append(candidate['title'])
            continue
        seen[fingerprint] = candidate
        result.append(candidate)
    return result
