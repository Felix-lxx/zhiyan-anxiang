from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.domain import (
    DecisionOption,
    DecisionPoint,
    MapObject,
    MapObjectType,
    Scene,
    SceneStatus,
    SceneTemplate,
)
from app.models.operations import DrillEvent, DrillSession, RobotAgent
from app.services.demo_community import get_or_create_demo_community
from app.services.scenes import create_scene, ensure_templates, update_charging_shed_parameters
from app.services.exercise_world import capture_world, frozen_world


DEMO_SCENE_NAME = "安巷社区三维数字孪生消防演练"

PARTICIPANTS = [
    {"role": "演练总控/导演", "name": "总控席", "ready": True},
    {"role": "应急指挥人员", "name": "社区指挥", "ready": True},
    {"role": "物业/网格员", "name": "物业处置组", "ready": True},
    {"role": "居民代表", "name": "3 号楼居民组", "ready": True},
]


def ensure_demo_experience(session: Session, owner_username: str) -> tuple:
    """Create or repair a fully playable demo, not only its community map."""
    community, _ = get_or_create_demo_community(session, owner_username)
    ensure_templates(session)
    template = session.scalar(select(SceneTemplate).where(SceneTemplate.code == "night_charging_shed_fire"))
    if template is None:
        raise RuntimeError("主案例模板初始化失败。")

    scene = session.scalar(
        select(Scene)
        .where(Scene.community_id == community.id, Scene.name == DEMO_SCENE_NAME)
        .options(selectinload(Scene.versions))
    )
    created = scene is None
    if created:
        scene = create_scene(session, community=community, template_id=template.id, name=DEMO_SCENE_NAME)
    if scene is None or not scene.versions:
        raise RuntimeError("主案例场景初始化失败。")

    version = scene.versions[-1]
    charging_shed = session.scalar(
        select(MapObject).where(
            MapObject.community_version_id == version.community_version_id,
            MapObject.object_type == MapObjectType.CHARGING_SHED,
        )
    )
    if charging_shed is None:
        raise RuntimeError("主案例缺少充电棚起火点。")

    # Entry is idempotent: returning to the demo must not overwrite edited
    # population/resources or create a fresh published version on every click.
    if created:
        scene = update_charging_shed_parameters(
            session,
            scene=scene,
            parameters={
                "fire_source_object_id": charging_shed.id,
                "start_time": "20:15",
                "wind_direction": "东北微风",
                "resident_count": 60,
                "hydrant_status": "available",
                "south_lane_status": "restricted",
            },
        )
    scene = session.scalar(select(Scene).where(Scene.id == scene.id).options(selectinload(Scene.versions)))
    version = scene.versions[-1]

    point = session.scalar(select(DecisionPoint).where(DecisionPoint.scene_version_id == version.id, DecisionPoint.name == "启动社区应急响应"))
    if point is None:
        point = DecisionPoint(
            scene_version_id=version.id,
            name="启动社区应急响应",
            trigger_condition="机器人复核火情并上报后",
            responsible_role="应急指挥人员",
            time_limit_seconds=30,
        )
        session.add(point)
        session.flush()
        session.add_all([
            DecisionOption(decision_point_id=point.id, label="立即启动响应", consequence="物业切断充电棚电源并组织 3 号楼居民疏散"),
            DecisionOption(decision_point_id=point.id, label="继续现场复核", consequence="机器人再次采样，响应时间延长并增加烟气暴露风险"),
        ])

    from app.services.scenario_tasks import ensure_standard_tasks, missing_tasks
    if not created and missing_tasks(session, version, 'night_charging_shed_fire') and version.status == SceneStatus.PUBLISHED:
        scene = update_charging_shed_parameters(session, scene=scene, parameters=dict(version.parameters))
        version = scene.versions[-1]
    ensure_standard_tasks(session, version, 'night_charging_shed_fire')

    scene.status = SceneStatus.PUBLISHED
    version.status = SceneStatus.PUBLISHED
    session.flush()

    drill = session.scalar(
        select(DrillSession)
        .where(DrillSession.scene_id == scene.id, DrillSession.scene_version_id == version.id,
               DrillSession.status.in_(["ready", "running", "paused"]))
        .order_by(DrillSession.created_at.desc())
    )
    if drill is not None and not (frozen_world(session, drill) or {}).get('tasks'):
        # Preserve the historical record, but never send a new user into an
        # unplayable legacy snapshot after the scene itself has been repaired.
        drill = None
    if drill is None:
        drill = DrillSession(
            scene_id=scene.id,
            scene_version_id=version.id,
            name="三维数字孪生演示场次",
            time_scale=2,
            participants=PARTICIPANTS,
            status="ready",
        )
        session.add(drill)
        session.flush()
        world = capture_world(session, version)
        session.add(RobotAgent(drill_session_id=drill.id, x=world["robot_origin"]["x"], y=world["robot_origin"]["y"], route=[]))
        session.add(DrillEvent(
            drill_session_id=drill.id,
            sequence=1,
            event_type="drill.created",
            actor="系统",
            message="三维数字孪生演示场次已就绪，可直接启动。",
            payload={"source": "demo-ready", "world": world},
            elapsed_seconds=0,
        ))

    session.commit()
    return community, scene, drill
