"""Revisions retain accepted actions and freeze both changed decisions and evidence."""
from copy import deepcopy

from fastapi import HTTPException

from app.models.domain import Scene
from app.services.agent_contract import tool_report
from app.services.agent_impact import impact_view, revision_difference
from app.services.knowledge import retrieve
from app.services.knowledge_applicability import situation


def replan(session, drill, run, data, request, identity):
    from app.services.agent_workflow import build_candidates, note, relevant_changes
    from app.services.agent_resources import completed_broadcast
    takeover = next((reason for state, reason in relevant_changes(session, run, run.observed_sequence, data)
                     if state == 'taken_over'), None)
    if takeover:
        from app.services.agent_claims import release
        run.status, run.reason = 'taken_over', takeover
        release(session, run.id)
        note(session, run, 'taken_over', takeover, data['elapsed_seconds'])
        session.commit()
        raise HTTPException(409, takeover)
    people = [p for p in data['simulation']['residents'] if p['id'] in run.scope['resident_ids']]
    remaining = [p['id'] for p in people if p['status'] != 'evacuated']
    if run.scope['priority_assist'] and any(p['status'] == 'evacuated' and p['vulnerable'] and not p.get('assisted') for p in people):
        raise HTTPException(409, '已有重点人员到场但未完成计划护送，不能通过重规划抹去缺项。请核对现场，必要时停止本计划后重新制定目标。')
    broadcast = completed_broadcast(session, run) if run.scope.get('robot_broadcast') else None
    if not remaining and (not run.scope.get('robot_broadcast') or broadcast):
        run.status = 'completed' if all(p.get('counted') for p in people) else 'awaiting_rollcall'
        run.reason = '目标行动与集合核验已完成。' if run.status == 'completed' else '目标已到场，行动证据已满足；请完成集合清点。'
        note(session, run, run.status, run.reason, data['elapsed_seconds'])
        session.commit()
        return
    original_scope = deepcopy(run.scope)
    scope = {**run.scope, 'resident_ids': remaining}
    if request.objective is not None:
        scope['objective'] = request.objective
    if request.forbidden_exits is not None:
        scope['forbidden_exits'] = sorted(set(request.forbidden_exits))
    if scope.get('exit_preference') in scope.get('forbidden_exits', []):
        scope['exit_preference'] = 'balanced'
    if broadcast:
        scope['robot_broadcast_evidence'] = broadcast
    candidates = build_candidates(session, drill, data, scope, run)
    changes = revision_difference(run, data, candidates, impact_view(session, run, data))
    changes.update(new_objective=scope.get('objective', 'balanced'), new_forbidden_exits=scope.get('forbidden_exits', []))
    scene = session.get(Scene, drill.scene_id)
    params = data['simulation'].get('world', {}).get('parameters', {})
    terms = run.goal + (' 道路封锁 改道 任务接续' if changes['impact']['changes_count'] else ' 目标约束 执行核验')
    knowledge = retrieve(session, identity.username, terms[:2000], community_id=scene.community_id,
        scenario='kitchen_fire' if params.get('fire_source_type') == 'kitchen' else 'charging_shed', drill_id=drill.id,
        situation=situation(data, scope))
    planning = tool_report(data, scope, candidates)
    planning['knowledge_assessment'] = knowledge['assessment']
    planning['trace'].insert(1, {'tool': 'search_knowledge', 'label': '重新检索修订依据', 'status': 'completed',
        'summary': f"本次命中 {len(knowledge['hits'])} 条发布资料，原版引用仍保留在修订记录中"})
    planning['trace'].insert(2, {'tool': 'assess_knowledge', 'label': '重新核对经验条件', 'status': 'completed',
        'summary': knowledge['assessment']['notice']})
    recovery = {'at_seconds': data['elapsed_seconds'], 'retained_arrived': len(people) - len(remaining),
        'remaining': len(remaining), 'active_escorts': sum(h['state'] != 'completed' and h['resident_id'] in remaining
            for h in data['simulation'].get('helpers', []))}
    run.evidence = [*run.evidence, {'revision': run.revision, 'steps': deepcopy(run.steps),
        'scope': original_scope, 'recovery': recovery}]
    # The monitor still owns the full original population; only future candidate
    # assignments exclude already-arrived residents.
    run.scope = {**scope, 'resident_ids': original_scope['resident_ids'], 'knowledge': knowledge,
                 'planning': planning, 'revision_context': changes}
    run.candidates, run.steps = candidates, []
    run.revision += 1
    run.approved_revision = None
    run.selected_candidate = None
    run.planner = 'local'
    run.planner_notice = '按当前现场重算剩余行动；原命令与位置继续保留。'
    run.status, run.reason, run.observed_sequence = 'awaiting_approval', '未到场部分已重新预演，请确认新版本。', data['latest_event_sequence']
    note(session, run, 'replanned', run.reason, data['elapsed_seconds'])
    session.commit()
