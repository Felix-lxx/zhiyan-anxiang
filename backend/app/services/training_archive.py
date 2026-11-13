"""Freeze factual end-of-drill evidence; generate drafts without publishing them."""
from copy import deepcopy
import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.domain import Scene
from app.models.knowledge import KnowledgeDocument
from app.models.operations import DrillEvent
from app.models.training import AssistantConversation, AssistantExchange, DrillArchive
from app.services.knowledge_ingestion import digest
from app.services.simulation_checkpoints import ENGINE_REVISION
from app.services.exposure import EXPOSURE_THRESHOLD


def fields(value, names):
    """Whitelist factual fields; never copy participant sessions or credentials."""
    return {key: deepcopy(value[key]) for key in names if key in value}


def archive_drill(session, drill, data, owner, *, backfill=False):
    existing = session.scalar(select(DrillArchive).where(DrillArchive.drill_session_id == drill.id))
    if existing:
        return existing
    if drill.status != 'ended' or not data.get('score'):
        raise HTTPException(409, '结束训练并冻结评分后才能生成档案。')
    scene = session.get(Scene, drill.scene_id)
    sim = data['simulation']
    world = sim.get('world') or {}
    people = sim['residents']
    tasks = data.get('tasks', [])
    events = list(session.scalars(select(DrillEvent).where(
        DrillEvent.drill_session_id == drill.id).order_by(DrillEvent.sequence)))
    archive_id = str(uuid5(NAMESPACE_URL, 'zhiyan-training-archive:' + drill.id))
    actual = {'arrived': sum(p['status'] == 'evacuated' for p in people),
              'exposed': sum(p.get('smoke_exposure', 0) > EXPOSURE_THRESHOLD for p in people),
              'queue_seconds': round(sum(p.get('queue_seconds', 0) for p in people))}
    metrics = {**actual, 'population':len(people), 'counted':sum(bool(p.get('counted')) for p in people),
        'cumulative_exposure': round(sum(p.get('smoke_exposure', 0) for p in people), 2),
        'priority_total':sum(bool(p.get('vulnerable')) for p in people),
        'priority_assisted':sum(p.get('vulnerable') and p.get('assisted', False) and p['status']=='evacuated' for p in people),
        'tasks_total':len(tasks), 'tasks_verified':sum(t['status']=='completed' for t in tasks),
        'fire_intensity':sim['fire']['intensity'], 'smoke_radius':sim['fire']['smoke_radius']}
    unresolved = {
        'unarrived':[p['id'] for p in people if p['status']!='evacuated'],
        'uncounted':[p['id'] for p in people if p['status']=='evacuated' and not p.get('counted')],
        'exposed':[p['id'] for p in people if p.get('smoke_exposure', 0)>EXPOSURE_THRESHOLD],
        'tasks':[t['id'] for t in tasks if t['status']!='completed'],
    }
    findings = []
    if unresolved['unarrived']: findings.append(f"结束时 {len(unresolved['unarrived'])} 人尚未到达集合点。")
    if unresolved['uncounted']: findings.append(f"已到场人员中 {len(unresolved['uncounted'])} 人尚未完成清点。")
    if unresolved['exposed']: findings.append(f"{len(unresolved['exposed'])} 人累计烟气暴露超过本模型阈值。")
    if unresolved['tasks']: findings.append(f"{len(unresolved['tasks'])} 项责任任务尚未完成核验。")
    if metrics['fire_intensity']>0: findings.append('结束时仍有仿真火情，疏散成绩不表示灭火完成。')
    if not findings: findings.append('本场人员到达、集合清点和责任任务均已核验；仍需结合事件核对操作条件。')
    important = [e for e in events if e.event_type in {'resident.command','indoor.door_changed',
        'task.accepted','task.arrived','task.completed','task.overdue','road.reopened','road.blocked',
        'inject.channel_blocked','inject.hydrant_failure','inject.resident_missing','vehicle.action_started',
        'vehicle.action_stopped','vehicle.dispatched','vehicle.arrived','robot.alarm_confirmed',
        'robot.broadcast_completed','drill.ended'}][-24:]
    evidence = [{'id':e.id, 'sequence':e.sequence, 'at_seconds':e.elapsed_seconds,
                 'kind':e.event_type, 'message':e.message[:240]} for e in important]
    basis = {'kind':'simulation_archive', 'archive_id':archive_id, 'drill_id':drill.id,
        'community_id':scene.community_id, 'scene_id':scene.id, 'scene_version_id':drill.scene_version_id,
        'drill_name':drill.name, 'observed_at':drill.elapsed_seconds, 'population':len(people), 'actual':actual,
        'parameters':deepcopy(world.get('parameters', {})), 'observed_engine_revision':None if backfill else ENGINE_REVISION,
        'result_kind':'incomplete' if any(unresolved.values()) else 'verified',
        'intervention_count':sum(e.event_type.startswith('inject.') for e in events),
        'event_sequence_from':events[0].sequence if events else 0,
        'event_sequence_to':events[-1].sequence if events else 0, 'events':evidence}
    conversation_count = session.scalar(select(func.count(AssistantExchange.id)).join(
        AssistantConversation, AssistantExchange.conversation_id == AssistantConversation.id).where(
        AssistantConversation.drill_session_id == drill.id, AssistantConversation.owner == owner)) or 0
    final_state = {
        'residents': [fields(person, ('id','label','status','vulnerable','assisted','counted','x','y','height',
            'building_id','floor','node_id','edge_id','exit','queue_seconds','smoke_exposure',
            'smoke_exposed_at_seconds','smoke_exposed_location','assembly_arrived_at_seconds')) for person in people],
        'tasks': [fields(task, ('id','title','kind','status','responsible_role','assignee','target_object_id',
            'deadline_at_seconds','action_completed_at','completed_on_time','evidence','blockers')) for task in tasks],
        'fire': deepcopy(sim['fire']),
        'indoor': deepcopy(sim.get('environment', {}).get('indoor')),
        'robot': fields(data.get('robot') or {}, ('name','state','battery','x','y','current_task','reason')),
        'vehicles': [fields(vehicle, ('id','name','state','x','y','mission_id','target_node_id','reason','service'))
                     for vehicle in sim.get('vehicles', [])],
    }
    if sim.get('community'):
        notification = sim['community']['summary']
        metrics['households_confirmed'] = notification['confirmed']
        unresolved['households_unconfirmed'] = notification['total'] - notification['confirmed']
        visits = sim['community'].get('visits', [])
        metrics['household_visits'] = len(visits)
        unresolved['household_visits_active'] = sum(v['state']!='completed' for v in visits)
        findings.append(f"分户通知：{notification['confirmed']}/{notification['total']} 户有收到回执；广播覆盖不等于住户确认。")
    payload = {'version':2, 'name':drill.name, 'scene_name':scene.name, 'scene_id':scene.id,
        'community_id':scene.community_id, 'elapsed_seconds':drill.elapsed_seconds,
        'scene_version_id':drill.scene_version_id, 'engine_revision':None if backfill else ENGINE_REVISION,
        'origin':'historical_reconstruction' if backfill else 'end_transaction',
        'score':deepcopy(data['score']), 'metrics':metrics, 'unresolved':unresolved, 'findings':findings,
        'community':deepcopy(sim.get('community')),
        'events':evidence, 'event_count':len(events), 'conversation_count_at_end':conversation_count,
        'experience_basis':basis, 'final_state':final_state}
    record = DrillArchive(id=archive_id, drill_session_id=drill.id, owner=owner, payload=payload,
        content_hash=digest(json.dumps(payload, sort_keys=True, ensure_ascii=False)))
    session.add(record)
    session.flush()
    # Draft factual observations for manual and agent-led runs, including failures.
    # Historical runs without a frozen world still receive an archive, not an
    # invented reusable model observation.
    if world.get('schema_version', 0)>=3:
        from app.services.knowledge import add_version
        document = KnowledgeDocument(id=str(uuid5(NAMESPACE_URL, 'zhiyan-archive-experience:'+archive_id)),
            owner=owner, community_id=scene.community_id, title=('训练观察：'+drill.name)[:200], category='experience',
            scenario='kitchen_fire' if world.get('indoor_environment') else 'charging_shed',
            source_url='', publisher='智演安巷 · 训练档案')
        session.add(document)
        session.flush()
        text = '\n'.join([f'来源：训练档案 {archive_id}，场景版本 {drill.scene_version_id}。',
            f"模型修订 {'历史记录未确认' if backfill else ENGINE_REVISION}；结束时刻 {drill.elapsed_seconds} 秒；参演 {len(people)} 人。",
            f"到场 {actual['arrived']} 人，清点 {metrics['counted']} 人，暴露超阈值 {actual['exposed']} 人，累计排队 {actual['queue_seconds']} 人秒。",
            *findings,
            '待核验任务：'+'；'.join(t['title'] for t in tasks if t['status']!='completed') if unresolved['tasks'] else '责任任务已全部核验。',
            '关键事件摘录：', *[f"{item['at_seconds']} 秒：{item['message']}" for item in evidence],
            '以上为本次训练事实，不推断某项操作的因果收益。',
            '待组织者补充：主要发现、适用条件、整改措施及下一次对照验证方法。'])
        add_version(session, document, [('训练事实与待审核经验', text)], extraction='training_archive')
        record.experience_document_id = document.id
    session.flush()
    return record


def archive_payload(session, record):
    from app.services.knowledge import document_payload
    document = session.get(KnowledgeDocument, record.experience_document_id) if record.experience_document_id else None
    return {'id':record.id, 'drill_id':record.drill_session_id, 'content_hash':record.content_hash,
        'created_at':record.created_at, 'data':record.payload,
        'experience':document_payload(session, document) if document else None}


def experience_sources(session, document_ids):
    """One provenance adapter for plan observations and automatic drill archives."""
    from app.models.knowledge import KnowledgeExperience
    result = {}
    ids = sorted(set(document_ids))
    for offset in range(0, len(ids), 500):
        part = ids[offset:offset+500]
        for source in session.scalars(select(KnowledgeExperience).where(KnowledgeExperience.document_id.in_(part))):
            result[source.document_id] = {**source.basis, 'basis_hash':source.basis_hash}
        # Retrieval needs provenance, not every resident's final state. Project
        # the JSON branch in SQL so published large-population runs stay bounded.
        statement = select(DrillArchive.experience_document_id, DrillArchive.payload['experience_basis'],
                           DrillArchive.content_hash).where(DrillArchive.experience_document_id.in_(part))
        for document_id, basis, content_hash in session.execute(statement):
            result[document_id] = {**basis, 'basis_hash':content_hash}
    return result
