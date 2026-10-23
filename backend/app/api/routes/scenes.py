from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import Scene, MapObject, MapObjectType
from app.schemas.scene import ChargingShedParametersUpdate, KitchenParametersUpdate, SceneCreate, SceneRead, SceneTemplateRead, SimulationPreviewRead, ScenarioCapabilitiesRead, FireSourceCandidateRead
from app.services.communities import get_community_or_none
from app.services.scenes import create_scene, list_scenes, list_templates, update_scene_parameters
from app.services.scenario_contracts import scene_contract, ScenarioUnavailable
from app.services.fire_sources import InvalidFireSource
from app.services.command_lock import serialized_command

router = APIRouter(tags=["scenes"])

def owned_community(session: Session, community_id: str, username: str):
    community = get_community_or_none(session, community_id)
    if community is None or community.owner.username != username:
        raise HTTPException(status_code=404, detail="未找到该社区项目。")
    return community

def serialize(scene: Scene) -> SceneRead:
    return SceneRead.model_validate(scene).model_copy(update={"capabilities": ScenarioCapabilitiesRead.model_validate(scene_contract(scene).payload())})

@router.get("/scene-templates", response_model=list[SceneTemplateRead])
def get_templates(identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    return [SceneTemplateRead.model_validate(item) for item in list_templates(session)]

@router.get("/communities/{community_id}/scenes", response_model=list[SceneRead])
def get_scenes(community_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    try:
        owned_community(session, community_id, identity.username)
        return [serialize(item) for item in list_scenes(session, community_id)]
    except HTTPException: raise
    except SQLAlchemyError as exc: raise HTTPException(status_code=503, detail="场景数据服务暂不可用。") from exc

@router.post("/communities/{community_id}/scenes", response_model=SceneRead, status_code=status.HTTP_201_CREATED)
def post_scene(community_id: str, payload: SceneCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    try:
        community = owned_community(session, community_id, identity.username)
        scene = create_scene(session, community=community, template_id=payload.template_id, name=payload.name)
        if scene is None: raise HTTPException(status_code=422, detail="模板不存在或社区尚无可用版本。")
        return serialize(scene)
    except ScenarioUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException: raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="场景草稿保存失败。") from exc

@router.patch("/scenes/{scene_id}/charging-shed-parameters", response_model=SceneRead)
@router.patch("/scenes/{scene_id}/parameters", response_model=SceneRead)
def patch_charging_shed_parameters(scene_id: str, payload: ChargingShedParametersUpdate | KitchenParametersUpdate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    try:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise HTTPException(status_code=404, detail="未找到该场景草稿。")
        owned_community(session, scene.community_id, identity.username)
        updated = update_scene_parameters(session, scene=scene, parameters=payload.model_dump())
        if updated is None:
            raise HTTPException(status_code=422, detail="起火点必须是该场景社区版本中的充电棚对象。")
        return serialize(updated)
    except InvalidFireSource as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ScenarioUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException: raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="场景参数保存失败。") from exc


@router.get("/scenes/{scene_id}/fire-sources", response_model=list[FireSourceCandidateRead])
def get_fire_sources(scene_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到该场景。")
    owned_community(session, scene.community_id, identity.username)
    version = max(scene.versions, key=lambda item: item.version_number, default=None)
    if version is None or not scene_contract(scene).available:
        return []
    from app.services.fire_sources import resolve_fire_source
    result = []
    kitchen = scene_contract(scene).code == 'kitchen_fire'
    for obj in session.scalars(select(MapObject).where(MapObject.community_version_id == version.community_version_id,
                                                      MapObject.object_type == (MapObjectType.BUILDING if kitchen else MapObjectType.CHARGING_SHED)).order_by(MapObject.created_at)):
        try:
            resolve_fire_source(session, version.community_version_id, {"fire_source_object_id": obj.id, 'fire_source_type': 'kitchen' if kitchen else 'charging_shed', 'fire_floor': 1, 'fire_room': 'east'})
        except InvalidFireSource:
            continue
        result.append({"id": obj.id, "name": obj.name, "object_type": obj.object_type.value, 'floors': max(1, min(20, int(obj.properties.get('floors', 6)))) if kitchen else 1})
    return result


@router.post('/scenes/{scene_id}/repair-tasks', response_model=SceneRead)
@serialized_command
def repair_scene_tasks(scene_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(404, '未找到该场景。')
    owned_community(session, scene.community_id, identity.username)
    session.execute(select(Scene.id).where(Scene.id == scene.id).with_for_update())
    version = max(scene.versions, key=lambda v: v.version_number)
    from app.services.scenario_tasks import missing_tasks, ensure_standard_tasks
    if not missing_tasks(session, version, scene_contract(scene).code):
        return serialize(scene)
    # Never mutate a published version or any frozen drill world.
    if scene.status.value == 'published' or version.status.value == 'published':
        scene = update_scene_parameters(session, scene=scene, parameters=dict(version.parameters))
        version = max(scene.versions, key=lambda v: v.version_number)
    ensure_standard_tasks(session, version, scene_contract(scene).code)
    session.commit()
    return serialize(scene)

def build_preview(session: Session, scene: Scene, minute: int, parameter_override: dict | None = None) -> SimulationPreviewRead:
    if minute < 0 or minute > 10:
        raise HTTPException(status_code=422, detail="预览时间必须在 0 至 10 分钟内。")
    if not scene.versions:
        raise HTTPException(status_code=422, detail="场景尚无可预览版本。")
    version = scene.versions[-1]
    parameters = {**version.parameters, **(parameter_override or {})}
    from app.services.scene_validation import validate_configuration
    validation = validate_configuration(session, scene, parameters)
    if not validation['passed']:
        raise HTTPException(status_code=422, detail='；'.join(validation['issues']))
    from app.services.exercise_world import capture_world
    from app.services.drill_simulation import simulate_residents
    import math
    world = capture_world(session, version, parameters)
    simulation = simulate_residents(world["road_network"], [], minute * 60, world=world)
    from app.services.vehicle_rescue import project_rescue_state
    simulation = project_rescue_state(world, [], minute * 60, simulation)
    intensity, radius = simulation["fire"]["intensity"], simulation["fire"]["smoke_radius"]
    fire = "初起" if intensity < 35 else "发展" if intensity < 70 else "猛烈"
    smoke = "轻微" if radius < 15 else "中等" if radius < 30 else "浓厚"
    risk = "关注" if intensity < 35 else "警戒" if intensity < 70 else "高风险"
    affected = [obj["name"] for obj in world["objects"] if math.dist((obj["x"], obj["y"]), (world["fire_origin"]["x"], world["fire_origin"]["y"])) <= radius]
    lane = parameters.get("south_lane_status", "restricted")
    route = "优先北侧出口，南门通道需现场复核。" if lane != "open" else "北、南两个出口均可作为候选撤离方向。"
    return SimulationPreviewRead(simulation=simulation, minute=minute, fire_level=fire, smoke_level=smoke, risk_level=risk, affected_targets=affected, route_advice=route, explanation="预览与正式演练共用同一社区版本、连续空间和规则仿真；当前操作只试算，不写入场景，也不下达撤离指令。")


@router.get("/scenes/{scene_id}/preview", response_model=SimulationPreviewRead)
def get_preview(scene_id: str, minute: int = 0, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None: raise HTTPException(status_code=404, detail="未找到该场景草稿。")
    owned_community(session, scene.community_id, identity.username)
    return build_preview(session, scene, minute)


@router.post("/scenes/{scene_id}/preview", response_model=SimulationPreviewRead)
def post_preview(scene_id: str, payload: ChargingShedParametersUpdate | KitchenParametersUpdate, minute: int = 0, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到该场景草稿。")
    owned_community(session, scene.community_id, identity.username)
    return build_preview(session, scene, minute, payload.model_dump())

@router.post('/scenes/{scene_id}/validate')
def validate_scene(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=session.get(Scene,scene_id)
    if scene is None: raise HTTPException(404,'未找到该场景草稿。')
    owned_community(session,scene.community_id,identity.username)
    from app.services.scene_validation import validate_configuration
    return validate_configuration(session, scene)
@router.post('/scenes/{scene_id}/publish')
def publish_scene(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=session.get(Scene,scene_id)
    if scene is None: raise HTTPException(404,'未找到该场景草稿。')
    owned_community(session,scene.community_id,identity.username)
    from app.services.scene_validation import validate_configuration
    result = validate_configuration(session, scene)
    if not result['passed']: raise HTTPException(422, '；'.join(result['issues']))
    from app.models.domain import SceneStatus
    scene.status=SceneStatus.PUBLISHED;scene.versions[-1].status=SceneStatus.PUBLISHED;session.commit();return {'status':'published','message':'场景已发布，可用于创建演练场次。'}
