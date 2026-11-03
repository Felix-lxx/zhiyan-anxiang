"""Turn completed, comparable simulation observations into reviewable drafts."""
from copy import deepcopy
import json
import math
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.agent import AgentDecisionCheck, AgentRun
from app.models.domain import Scene
from app.models.knowledge import KnowledgeDocument, KnowledgeExperience
from app.models.operations import DrillCommand, DrillEvent, DrillSession
from app.services.exercise_world import frozen_world
from app.services.knowledge import add_version, document_payload, require_community
from app.services.knowledge_ingestion import digest


def existing_experience(session, owner, check_id):
    source = session.scalar(select(KnowledgeExperience).where(KnowledgeExperience.owner == owner,
                                                            KnowledgeExperience.decision_check_id == check_id))
    if source:
        document = session.get(KnowledgeDocument, source.document_id)
        if document:
            return {'created': False, 'document': document_payload(session, document, detail=True)}
    return None


def draft_from_outcome(session, run_id, revision, identity):
    run = session.get(AgentRun, run_id)
    if not run or run.actor != identity.username:
        raise HTTPException(404, '未找到该目标计划。')
    drill = session.get(DrillSession, run.drill_session_id)
    scene = session.get(Scene, drill.scene_id) if drill else None
    if not scene:
        raise HTTPException(404, '来源场次或场景已不可访问。')
    require_community(session, scene.community_id, identity.username)
    check = session.scalar(select(AgentDecisionCheck).where(AgentDecisionCheck.run_id == run.id,
                                                          AgentDecisionCheck.revision == revision))
    if not check:
        raise HTTPException(404, '未找到该批准版本的观察记录。')
    old = existing_experience(session, identity.username, check.id)
    if old:
        return old
    result = check.result or {}
    if not check.basis.get('resident_ids') or check.status != 'observed' or not result.get('comparable') or result.get('early_ended') or result.get('matched') != len(check.basis['resident_ids']):
        raise HTTPException(409, '观察尚未完成或不具备同口径比较条件，请先完成结果核对。')
    metrics = {'arrived', 'exposed', 'queue_seconds'}
    if any(not isinstance(values, dict) or not metrics.issubset(values)
           for values in (check.basis.get('predicted'), result.get('actual'), result.get('delta'))):
        raise HTTPException(409, '这份历史记录缺少完整指标，不能自动生成经验，请保留原始复盘。')
    if any(isinstance(values[key], bool) or not isinstance(values[key], (int, float)) or not math.isfinite(values[key])
           for values in (check.basis['predicted'], result['actual'], result['delta']) for key in metrics):
        raise HTTPException(409, '这份观察包含无效指标，请核对原始记录。')
    world = frozen_world(session, drill) or {}
    parameters = world.get('parameters', {})
    basis = {'kind': 'simulation_observation', 'run_id': run.id, 'drill_id': drill.id,
        'community_id': scene.community_id, 'scene_id': scene.id,
        'scene_version_id': run.scope.get('scene_version_id'), 'revision': check.revision,
        'drill_name': drill.name, 'goal': run.goal, 'title': check.basis['title'],
        'observed_at': result['observed_at'], 'forecast_at': check.basis['forecast_at'],
        'approved_at': check.basis['approved_at'], 'forecast_seconds': check.basis['forecast_seconds'],
        'population': len(check.basis['resident_ids']), 'predicted': deepcopy(check.basis['predicted']),
        'forecast_engine_revision': check.basis.get('forecast_engine_revision'),
        'observed_engine_revision': result.get('observed_engine_revision'),
        'actual': deepcopy(result['actual']), 'delta': deepcopy(result['delta']),
        'event_sequence_from': check.basis['after_sequence'], 'event_sequence_to': result['last_event_sequence'],
        'intervention_count': result['intervention_count'],
        'parameters': {key: parameters[key] for key in ('fire_source_type', 'fire_source_object_id', 'fire_floor', 'fire_room',
            'resident_count', 'stair_width', 'south_lane_status', 'room_door_state') if key in parameters}}
    ids = {event['id'] for event in result.get('interventions', [])}
    commands = list(set(check.basis['command_ids']))
    for offset in range(0, len(commands), 500):
        for event_ids in session.scalars(select(DrillCommand.event_ids).where(DrillCommand.drill_session_id == drill.id,
                DrillCommand.command_id.in_(commands[offset:offset + 500]))):
            ids.update(event_ids or [])
    events, event_ids = [], sorted(ids)
    for offset in range(0, len(event_ids), 500):
        events.extend(session.scalars(select(DrillEvent).where(DrillEvent.drill_session_id == drill.id,
            DrillEvent.id.in_(event_ids[offset:offset + 500]), DrillEvent.sequence <= result['last_event_sequence'],
            DrillEvent.elapsed_seconds <= result['observed_at']).order_by(DrillEvent.sequence).limit(16)))
    events = sorted(events, key=lambda event: event.sequence)[:16]
    basis['events'] = [{'id': event.id, 'sequence': event.sequence, 'at_seconds': event.elapsed_seconds,
                       'kind': event.event_type, 'message': event.message[:240]} for event in events]
    title = f"复盘观察：{drill.name} · 批准版本 {revision}"[:200]
    text = [f'复盘经验草稿：{title}', f"来源：本平台仿真，冻结场景版本 {basis['scene_version_id']}。",
        f"目标：{run.goal}", f"观察窗口：{basis['forecast_at']}—{basis['observed_at']} 秒，核对 {basis['population']} 名居民。"]
    for key, label, unit in [('arrived', '到集合点', '人'), ('exposed', '暴露超阈值', '人'), ('queue_seconds', '累计排队', '人秒')]:
        text.append(f"{label}：预测 {basis['predicted'][key]}{unit}，观察 {basis['actual'][key]}{unit}，差值 {basis['delta'][key]:+}{unit}。")
    text += [f"批准延迟 {result['approval_delay_seconds']} 秒；期间记录 {basis['intervention_count']} 条场次变化。",
        '复盘线索：结合通知、通行、护送和期间事件，定位预测偏差及需要再次比较的条件。',
        '待组织者补充：记录本次发现、适用条件与下一次验证办法；核对来源事实后提交审核。']
    document_id = str(uuid5(NAMESPACE_URL, 'zhiyan-experience:'+identity.username+':'+check.id))
    try:
        document = KnowledgeDocument(id=document_id, owner=identity.username, community_id=scene.community_id,
            title=title, category='experience', scenario='kitchen_fire' if parameters.get('fire_source_type') == 'kitchen' else 'charging_shed',
            source_url='', publisher='智演安巷 · 演练组织者复盘')
        session.add(document)
        session.flush()
        add_version(session, document, [('同口径观察与待审核说明', '\n'.join(text))], extraction='simulation_observation')
        session.add(KnowledgeExperience(owner=identity.username, decision_check_id=check.id,
            document_id=document.id, basis=basis, basis_hash=digest(json.dumps(basis, ensure_ascii=False, sort_keys=True))))
        session.commit()
    except IntegrityError:
        session.rollback()
        old = existing_experience(session, identity.username, check.id)
        if old:
            return old
        raise HTTPException(409, '资料正在被同时保存，请稍后重新读取。') from None
    return {'created': True, 'document': document_payload(session, document, detail=True)}
