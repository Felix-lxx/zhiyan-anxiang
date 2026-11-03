"""Explicit goal constraints shared by drafting, forecasting and recovery."""
import re

from fastapi import HTTPException


OBJECTIVES = {'balanced': '风险与效率均衡', 'low_exposure': '优先降低暴露', 'fast_arrival': '优先尽快到场'}
RANKING_METHODS = {'balanced': '按预演状态分、暴露人数、到场人数、排队时间依次排序。',
    'low_exposure': '按暴露人数、到场人数、排队时间依次排序。',
    'fast_arrival': '按预演时刻到场人数、暴露人数、排队时间依次排序；不表示全程最终耗时。'}


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
    return {'floors': sorted(set(floors)), 'objective': objective, 'forbidden_exits': sorted(forbidden)}


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
