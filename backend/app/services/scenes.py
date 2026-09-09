from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.domain import Community, DecisionOption, DecisionPoint, MapObject, MapObjectType, Scene, SceneStatus, SceneTemplate, SceneVersion
from app.services.map_objects import current_version


TEMPLATES = [
    {"code": "night_charging_shed_fire", "name": "夜间电动自行车充电棚火灾", "description": "适用于集中充电棚起火、夜间居民疏散与消防通道占用处置。", "defaults": {"time": "20:15", "fire_source_type": "charging_shed", "wind": "微风", "initial_stage": "smoldering"}},
    {"code": "kitchen_fire", "name": "居民厨房火灾", "description": "适用于楼栋室内初起火灾、楼道疏散和物业响应。", "defaults": {"time": "18:30", "fire_source_type": "kitchen", "wind": "无", "initial_stage": "smoldering"}},
]


def ensure_templates(session: Session) -> None:
    existing = {item.code for item in session.scalars(select(SceneTemplate))}
    for template in TEMPLATES:
        if template["code"] not in existing:
            session.add(SceneTemplate(**template))
    session.commit()


def list_templates(session: Session) -> list[SceneTemplate]:
    ensure_templates(session)
    # 主案例模板置顶，使场景工作台的默认选择与比赛演示案例一致。
    return list(session.scalars(select(SceneTemplate).order_by(SceneTemplate.code.desc())))


def list_scenes(session: Session, community_id: str) -> list[Scene]:
    statement = select(Scene).where(Scene.community_id == community_id).options(selectinload(Scene.versions)).order_by(Scene.updated_at.desc())
    return list(session.scalars(statement))


def create_scene(session: Session, *, community: Community, template_id: str, name: str) -> Scene | None:
    template = session.get(SceneTemplate, template_id)
    version = current_version(community)
    if template is None or version is None:
        return None
    scene = Scene(community_id=community.id, template_id=template.id, name=name, status=SceneStatus.DRAFT)
    session.add(scene)
    session.flush()
    session.add(SceneVersion(scene_id=scene.id, community_version_id=version.id, version_number=1, status=SceneStatus.DRAFT, parameters=template.defaults))
    session.commit()
    return session.scalar(select(Scene).where(Scene.id == scene.id).options(selectinload(Scene.versions)))


def update_charging_shed_parameters(session: Session, *, scene: Scene, parameters: dict) -> Scene | None:
    version = scene.versions[-1] if scene.versions else None
    if version is None:
        return None
    source = session.scalar(select(MapObject).where(MapObject.id == parameters["fire_source_object_id"], MapObject.community_version_id == version.community_version_id))
    if source is None or source.object_type != MapObjectType.CHARGING_SHED:
        return None
    merged_parameters = {**version.parameters, **parameters, "fire_source_type": "charging_shed"}
    if version.status == SceneStatus.PUBLISHED or scene.status == SceneStatus.PUBLISHED:
        # Published versions are immutable evidence. Editing one creates a new
        # draft while preserving its decision flow for continued authoring.
        draft = SceneVersion(
            scene_id=scene.id,
            community_version_id=version.community_version_id,
            version_number=version.version_number + 1,
            status=SceneStatus.DRAFT,
            parameters=merged_parameters,
        )
        session.add(draft)
        session.flush()
        cloned_points: dict[str, DecisionPoint] = {}
        for point in version.decision_points:
            clone = DecisionPoint(
                scene_version_id=draft.id,
                name=point.name,
                trigger_condition=point.trigger_condition,
                responsible_role=point.responsible_role,
                time_limit_seconds=point.time_limit_seconds,
            )
            session.add(clone)
            session.flush()
            cloned_points[point.id] = clone
        for point in version.decision_points:
            for option in point.options:
                next_point = cloned_points.get(option.next_decision_point_id) if option.next_decision_point_id else None
                session.add(DecisionOption(
                    decision_point_id=cloned_points[point.id].id,
                    label=option.label,
                    consequence=option.consequence,
                    next_decision_point_id=next_point.id if next_point else None,
                ))
        scene.status = SceneStatus.DRAFT
    else:
        version.parameters = merged_parameters
    session.commit()
    return session.scalar(select(Scene).where(Scene.id == scene.id).options(selectinload(Scene.versions)))
