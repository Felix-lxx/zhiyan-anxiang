"""Explicit goal constraints shared by drafting, forecasting and recovery."""
import re

from fastapi import HTTPException


OBJECTIVES = {'balanced': '风险与效率均衡', 'low_exposure': '优先降低暴露', 'fast_arrival': '优先尽快到场'}
RANKING_METHODS = {'balanced': '按预演状态分、暴露人数、到场人数、排队时间依次排序。',
    'low_exposure': '按暴露人数、到场人数、排队时间依次排序。',
    'fast_arrival': '按预演时刻到场人数、暴露人数、排队时间依次排序；不表示全程最终耗时。'}


def unsupported_goal_parts(goal):
    """Find requested actions outside this planner's executable contract."""
    patterns = {
        '伤员转运': r'转运|送医|医疗移交|接运',
    }
    found = []
    for clause in re.split(r'[，,。；;！？!?\n]|但是|同时|然后|并且|并|再', goal):
        for label, pattern in patterns.items():
            for match in re.finditer(pattern, clause):
                prefix = clause[max(0, match.start() - 12):match.start()]
                if re.search(r'(?:不要|不用|无需|不必|禁止|暂不|勿|避免|不需要|不安排|不)(?:.{0,8})$', prefix):
                    continue
                if re.search(r'不要|不用|无需|禁止|暂不|不需要', match.group()):
                    continue
                if label not in found:
                    found.append(label)
    return found


def validate_goal_capabilities(goal):
    unsupported = unsupported_goal_parts(goal)
    if unsupported:
        raise HTTPException(422, '本次目标包含尚未接入自动编排的部分：' + '、'.join(unsupported)
            + '。请从“车辆调度”单独预览并确认伤员接运；当前目标计划支持室外消防车到场喷水、居民疏散、分流、护送及责任任务核验。')


def suppression_intent(goal):
    requested, excluded = False, False
    pattern = r'(?:消防车|水源|供水).{0,16}(?:喷水|压制|灭火|到场)|(?:先|等待).{0,8}(?:喷水|压制).{0,12}(?:疏散|撤离|放行)'
    negative = r'不要|不用|无需|不必|禁止|暂不|勿|避免|不需要|不安排|不'
    for clause in re.split(r'[，,。；;！？!?\n]|但是|同时|然后|并且|并|再', goal):
        for match in re.finditer(pattern, clause):
            prefix = clause[max(0, match.start() - 12):match.start()]
            negated = re.search(r'(?:' + negative + r')(?:.{0,8})$', prefix) or re.search(
                r'(?:' + negative + r').{0,4}(?:喷水|压制|灭火|到场)', match.group())
            if negated:
                excluded = True
            else:
                requested = True
    if requested and excluded:
        raise HTTPException(422, '目标同时要求和禁止消防车喷水，请明确本次是否允许该动作。')
    return requested, excluded


def goal_constraints(request):
    if re.search(r'(?:不要|暂不|不)(?:疏散|撤离|护送)[^，。；;]{0,12}[\d一二三四五六七八九十]+\s*层', request.goal):
        raise HTTPException(422, '暂不处理的楼层请从目标范围中排除，并明确写出要疏散的人员。')
    floors = list(getattr(request, 'floors', []) or [])
    if not floors:
        # Resolve explicit floor expressions, never infer a floor from a building number.
        digits = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
        for value in re.findall(r'(?<![\d.一二三四五六七八九十百])([1-9]\d{0,2}|[一二三四五六七八九十百]+)\s*(?:层|楼)(?![栋号])', request.goal):
            if value.isdigit():
                floor = int(value)
            elif value in {'一百', '百'}:
                floor = 100
            elif '十' in value and value.count('十') == 1:
                tens, units = value.split('十')
                if (tens and tens not in digits) or (units and units not in digits):
                    raise HTTPException(422, '无法明确识别楼层，请在目标约束中输入楼层。')
                floor = digits.get(tens, 1) * 10 + digits.get(units, 0)
            elif value in digits:
                floor = digits[value]
            else:
                raise HTTPException(422, '无法明确识别楼层，请在目标约束中输入楼层。')
            if not 1 <= floor <= 100:
                raise HTTPException(422, '目标楼层超出支持范围，请输入 1–100 层。')
            floors.append(floor)
        # Ambiguous ranges must be made explicit instead of evacuating the whole building.
        if re.search(r'[\d一二三四五六七八九十]+\s*(?:到|至|[-—~～])\s*[\d一二三四五六七八九十]+\s*层', request.goal):
            raise HTTPException(422, '楼层范围请在目标约束中逐项选择，避免漏选楼层。')
    objective = getattr(request, 'objective', 'balanced')
    if objective == 'balanced':
        if any(word in request.goal for word in ('降低暴露', '减少暴露', '烟气最小', '降低烟气')):
            objective = 'low_exposure'
        elif any(word in request.goal for word in ('最快', '尽快到达', '最短时间')):
            objective = 'fast_arrival'
    forbidden = set(getattr(request, 'forbidden_exits', []) or [])
    for name, key in [('北', 'north'), ('南', 'south')]:
        if re.search(r'(?:禁止|禁用|不要使用|不要走|不使用|不走|避开)\s*' + name + r'(?:门|侧出口)', request.goal):
            forbidden.add(key)
    if len(forbidden) == 2:
        raise HTTPException(422, '两个出口均被禁止，无法形成疏散计划。请调整约束或先处理通道。')
    suppression, suppression_forbidden = suppression_intent(request.goal)
    return {'floors': sorted(set(floors)), 'objective': objective, 'forbidden_exits': sorted(forbidden),
            'vehicle_suppression': suppression, 'vehicle_suppression_forbidden': suppression_forbidden}


def rank_candidate(candidate, objective='balanced'):
    metrics = candidate['metrics']
    if objective == 'fast_arrival':
        return (not candidate['can_apply'], -metrics['arrived'], metrics['exposed'], metrics['queue_seconds'])
    if objective == 'balanced':
        return (not candidate['can_apply'], -metrics['score'], metrics['exposed'], -metrics['arrived'], metrics['queue_seconds'])
    return (not candidate['can_apply'], metrics['exposed'], -metrics['arrived'], metrics['queue_seconds'])


def tool_report(data, scope, candidates):
    """Public summaries of actual domain outputs, never a model's hidden reasoning."""
    checks = []
    for candidate in candidates:
        failures = []
        if candidate['metrics']['unreachable']:
            failures.append(f"{candidate['metrics']['unreachable']} 名居民路线不可达")
        support = candidate.get('robot_support')
        if support and not support['can_apply']:
            failures.append(support['notice'])
        vehicle = candidate.get('vehicle_support')
        if vehicle and not vehicle['can_apply']:
            failures.append(vehicle['notice'])
        if scope.get('vehicle_suppression') and not vehicle:
            failures.append('目标要求先由消防车喷水，但该候选没有车辆压制与居民放行依赖')
        if scope.get('vehicle_suppression_forbidden') and vehicle:
            failures.append('目标禁止消防车喷水，该候选包含被禁止的动作')
        assist = candidate.get('assist_resource') or {}
        if assist.get('required') and not assist.get('capacity'):
            failures.append('本场无可用护送岗位')
        violations = [p['id'] for p in candidate['assignments'] if p['exit'] in scope.get('forbidden_exits', [])]
        if violations:
            failures.append(f'{len(violations)} 名居民使用了禁用出口')
        if failures:
            candidate['can_apply'] = False
            candidate['reason'] = '；'.join(failures)
        checks.append({'candidate_id': candidate['id'], 'valid': bool(candidate['can_apply']), 'blockers': failures})
    usable = [c for c in candidates if c['can_apply']]
    recommended = min(usable, key=lambda c: rank_candidate(c, scope.get('objective', 'balanced'))) if usable else None
    return {'version': 1, 'at_seconds': data['elapsed_seconds'], 'event_sequence': data['latest_event_sequence'],
            'objective': scope.get('objective', 'balanced'), 'objective_label': OBJECTIVES[scope.get('objective', 'balanced')],
            'ranking_method': RANKING_METHODS[scope.get('objective', 'balanced')],
            'recommended_candidate_id': recommended['id'] if recommended else None,
            'mode': 'deterministic', 'notice': '按真实路线、岗位和同一时域仿真比较；尚未下达指令。',
            'checks': checks,
            'trace': [
                {'tool': 'observe_scene', 'label': '读取现场', 'status': 'completed',
                 'summary': f"事件 {data['latest_event_sequence']}，目标 {len(scope['resident_ids'])} 人"},
                {'tool': 'check_routes_resources', 'label': '路线与资源校验', 'status': 'completed',
                 'summary': f"{len(usable)}/{len(candidates)} 个方案满足当前通行与资源条件"},
                {'tool': 'compare_candidates', 'label': '同起点仿真比较', 'status': 'completed',
                 'summary': f"预演 {candidates[0]['forecast_seconds'] if candidates else 0} 秒，按{OBJECTIVES[scope.get('objective', 'balanced')]}推荐"}
            ]}
