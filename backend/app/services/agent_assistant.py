"""Read-only current-plan facts for chat; historical chat never reads live plans."""
from sqlalchemy import select

from app.models.agent import AgentRun
from app.services.agent_impact import impact_view

LABELS = {'awaiting_approval': '待确认', 'executing': '执行中', 'waiting': '等待条件',
          'needs_review': '需要修订', 'awaiting_rollcall': '等待集合清点', 'completed': '已完成',
          'stopped': '已停止', 'taken_over': '已被接管', 'unfinished': '未完成'}
ACTIVE = {'awaiting_approval', 'executing', 'waiting', 'needs_review', 'awaiting_rollcall'}


def add_plan_context(session, data, context, owner, question):
    if context['historical']:
        return ''
    if not any(word in question for word in ('计划', '修订', '重新比较', '改道', '封路', '执行')):
        return ''
    runs = list(session.scalars(select(AgentRun).where(AgentRun.drill_session_id == data['id'], AgentRun.actor == owner)
        .order_by((AgentRun.status == 'needs_review').desc(), AgentRun.status.in_(ACTIVE).desc(), AgentRun.created_at.desc()).limit(2)))
    if not runs:
        return ''
    facts, explanations = [], []
    source_index = max((int(source['id'][1:]) for source in context['sources'] if source['id'].startswith('S')), default=0)
    people = {p['id']: p for p in data['simulation']['residents']}
    for index, run in enumerate(runs, source_index + 1):
        impact = impact_view(session, run, data)
        selected = [people[pid] for pid in run.scope['resident_ids'] if pid in people]
        counts = {'total': len(selected), 'arrived': sum(p['status'] == 'evacuated' for p in selected),
                  'counted': sum(bool(p.get('counted')) for p in selected)}
        detail = (f"版本 {run.revision}，{LABELS.get(run.status, run.status)}。目标 {counts['total']} 人，"
            f"到场 {counts['arrived']} 人，已清点 {counts['counted']} 人。{run.reason}"
            + (f"原路线相关变化关联 {impact['affected_count']} 名未到场居民、{impact['step_count']} 个步骤。" if impact['changes_count'] else ''))
        context['sources'].append({'id': f'S{index}', 'title': '本场目标计划与执行', 'detail': detail})
        facts.append({'id': run.id, 'revision': run.revision, 'goal': run.goal[:300], 'status': run.status,
            'counts': counts, 'reason': run.reason, 'source_id': f'S{index}',
            'impact': {key: impact[key] for key in ('affected_count', 'step_count', 'changes_count', 'changes', 'events_truncated')}})
        explanations.append(f"本场目标计划：{detail} [S{index}]")
    context['agent_plans'] = facts
    return '\n'.join(explanations) + '\n修订需要重新预演和人工确认，已受理行动继续；场景对话不会自动改派。'
