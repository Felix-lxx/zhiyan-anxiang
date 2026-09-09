from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.core.database import get_db
from app.models.domain import MapObject, MapObjectType, Scene
from app.schemas.scene import ChargingShedParametersUpdate, SceneCreate, SceneRead, SceneTemplateRead, SimulationPreviewRead
from app.services.communities import get_community_or_none
from app.services.scenes import create_scene, list_scenes, list_templates, update_charging_shed_parameters

router = APIRouter(tags=["scenes"])

def owned_community(session: Session, community_id: str, username: str):
    community = get_community_or_none(session, community_id)
    if community is None or community.owner.username != username:
        raise HTTPException(status_code=404, detail="未找到该社区项目。")
    return community

def serialize(scene: Scene) -> SceneRead:
    return SceneRead.model_validate(scene)

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
    except HTTPException: raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="场景草稿保存失败。") from exc

@router.patch("/scenes/{scene_id}/charging-shed-parameters", response_model=SceneRead)
def patch_charging_shed_parameters(scene_id: str, payload: ChargingShedParametersUpdate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    try:
        scene = session.get(Scene, scene_id)
        if scene is None:
            raise HTTPException(status_code=404, detail="未找到该场景草稿。")
        owned_community(session, scene.community_id, identity.username)
        updated = update_charging_shed_parameters(session, scene=scene, parameters=payload.model_dump())
        if updated is None:
            raise HTTPException(status_code=422, detail="起火点必须是该场景社区版本中的充电棚对象。")
        return serialize(updated)
    except HTTPException: raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="场景参数保存失败。") from exc

def build_preview(session: Session, scene: Scene, minute: int, parameter_override: dict | None = None) -> SimulationPreviewRead:
    if minute < 0 or minute > 10:
        raise HTTPException(status_code=422, detail="预览时间必须在 0 至 10 分钟内。")
    if not scene.versions:
        raise HTTPException(status_code=422, detail="场景尚无可预览版本。")
    version = scene.versions[-1]
    parameters = {**version.parameters, **(parameter_override or {})}
    if parameter_override:
        parameters["fire_source_type"] = "charging_shed"
    source = session.scalar(select(MapObject).where(MapObject.id == parameters.get("fire_source_object_id"), MapObject.community_version_id == version.community_version_id))
    if source is None or source.object_type != MapObjectType.CHARGING_SHED:
        raise HTTPException(status_code=422, detail="起火点必须是当前社区版本中的充电棚对象。")
    from app.services.exercise_world import capture_world
    from app.services.drill_simulation import simulate_residents
    import math
    world = capture_world(session, version, parameters)
    simulation = simulate_residents(world["road_network"], [], minute * 60, world=world)
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
    parameters = scene.versions[-1].parameters if scene.versions else {}
    if parameters.get("fire_source_type") != "charging_shed": raise HTTPException(status_code=422, detail="请先保存充电棚火灾参数后再预览。")
    return build_preview(session, scene, minute)


@router.post("/scenes/{scene_id}/preview", response_model=SimulationPreviewRead)
def post_preview(scene_id: str, payload: ChargingShedParametersUpdate, minute: int = 0, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)):
    scene = session.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="未找到该场景草稿。")
    owned_community(session, scene.community_id, identity.username)
    return build_preview(session, scene, minute, payload.model_dump())

@router.post('/scenes/{scene_id}/validate')
def validate_scene(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=session.get(Scene,scene_id)
    if scene is None: raise HTTPException(404,'未找到该场景草稿。')
    owned_community(session,scene.community_id,identity.username);p=scene.versions[-1].parameters if scene.versions else {}
    issues=[]
    for key,label in [('fire_source_object_id','起火点'),('start_time','起火时间'),('wind_direction','风向'),('resident_count','参演居民数')]:
        if not p.get(key): issues.append(f'缺少{label}')
    return {'passed':not issues,'issues':issues,'message':'场景校验通过，可发布。' if not issues else '场景尚不能发布。'}
@router.post('/scenes/{scene_id}/publish')
def publish_scene(scene_id:str,identity:AuthenticatedIdentity=Depends(get_current_identity),session:Session=Depends(get_db)):
    scene=session.get(Scene,scene_id)
    if scene is None: raise HTTPException(404,'未找到该场景草稿。')
    owned_community(session,scene.community_id,identity.username);p=scene.versions[-1].parameters if scene.versions else {}
    if not all(p.get(k) for k in ['fire_source_object_id','start_time','wind_direction','resident_count']): raise HTTPException(422,'场景未通过完整性校验，不能发布。')
    from app.models.domain import SceneStatus
    scene.status=SceneStatus.PUBLISHED;scene.versions[-1].status=SceneStatus.PUBLISHED;session.commit();return {'status':'published','message':'场景已发布，可用于创建演练场次。'}
