"""Bounded, read-only cross-scene history. Never advances the simulation."""
from datetime import UTC, datetime
from sqlalchemy import func, or_, select
from app.models.domain import Scene
from app.models.operations import DrillEvent, DrillScore, DrillSession


def history_page(session, community_id, *, page=1, page_size=20, search='',
                 status='all', scene_id=None, start=None, end=None, sort='newest'):
    scope = Scene.community_id == community_id
    filters = [scope]
    if search.strip():
        filters.append(or_(DrillSession.name.icontains(search.strip(), autoescape=True),
                           Scene.name.icontains(search.strip(), autoescape=True)))
    if status != 'all':
        filters.append(DrillSession.status == status)
    if scene_id:
        filters.append(Scene.id == scene_id)
    if start:
        filters.append(DrillSession.created_at >= start)
    if end:
        filters.append(DrillSession.created_at <= end)
    count = select(func.count()).select_from(DrillSession).join(Scene, Scene.id == DrillSession.scene_id)
    total = session.scalar(count.where(scope))
    matched = session.scalar(count.where(*filters))
    page = min(page, max(1, (matched + page_size - 1) // page_size))
    # Extract a single scalar from the frozen creation event, not all residents or events.
    population = select(DrillEvent.payload['world']['parameters']['resident_count'].as_integer()).where(
        DrillEvent.drill_session_id == DrillSession.id, DrillEvent.event_type == 'drill.created'
    ).order_by(DrillEvent.sequence).limit(1).correlate(DrillSession).scalar_subquery()
    query = select(DrillSession, Scene.name, DrillScore, population).join(
        Scene, Scene.id == DrillSession.scene_id).outerjoin(DrillScore, DrillScore.drill_session_id == DrillSession.id)
    order = [DrillSession.created_at.desc(), DrillSession.id.desc()]
    if sort == 'oldest':
        order = [DrillSession.created_at.asc(), DrillSession.id.asc()]
    elif sort == 'score':
        order.insert(0, func.coalesce(DrillScore.total_score, -1).desc())
    now = datetime.now(UTC)

    def serialize(row):
        drill, scene_name, score, residents = row
        created = drill.created_at.replace(tzinfo=UTC) if drill.created_at.tzinfo is None else drill.created_at
        elapsed = drill.elapsed_seconds
        if drill.status == 'running' and drill.started_at:
            started = drill.started_at.replace(tzinfo=UTC) if drill.started_at.tzinfo is None else drill.started_at
            elapsed += max(0, int((now - started).total_seconds() * drill.time_scale))
        return dict(id=drill.id, sceneId=drill.scene_id, sceneName=scene_name, name=drill.name,
                    status=drill.status, created_at=created.isoformat(), elapsed_seconds=max(0, elapsed),
                    resident_count=max(1, min(1000, residents)) if residents is not None else None,
                    score=None if score is None else dict(total_score=score.total_score,
                        details=[], recommendations=score.recommendations))

    rows = session.execute(query.where(*filters).order_by(*order).offset((page-1)*page_size).limit(page_size))
    unfinished = session.execute(query.where(scope, DrillSession.status.in_(['running', 'paused']))
        .order_by(DrillSession.created_at.desc(), DrillSession.id.desc()).limit(1)).first()
    return dict(items=[serialize(row) for row in rows], total=total, matched=matched,
                page=page, page_size=page_size, latest_unfinished=serialize(unfinished) if unfinished else None)
