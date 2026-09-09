from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import (
    Community,
    CommunityStatus,
    CommunityVersion,
    CommunityVersionStatus,
    MapObject,
    MapObjectType,
    RoadEdge,
    RoadEdgeStatus,
    RoadNode,
)
from app.services.access import ensure_development_user
from app.services.communities import get_community_or_none


DEMO_COMMUNITY_NAME = "安巷社区 · 夜间充电棚火灾主案例"


def get_or_create_demo_community(session: Session, owner_username: str) -> tuple[Community, bool]:
    """生成比赛主案例的固定底图；同一账号重复调用时返回已有案例。"""

    existing = session.scalar(
        select(Community)
        .join(Community.owner)
        .where(Community.owner.has(username=owner_username), Community.name == DEMO_COMMUNITY_NAME)
    )
    if existing is not None:
        return get_community_or_none(session, existing.id), False  # type: ignore[return-value]

    owner = ensure_development_user(session, owner_username)
    community = Community(
        name=DEMO_COMMUNITY_NAME,
        address="示例路 18 号",
        description="固定演示底图：20:15，3 号楼旁电动自行车充电棚起火；南门消防通道存在占用风险，东侧消火栓待核验。",
        status=CommunityStatus.DRAFT,
        owner_id=owner.id,
    )
    session.add(community)
    session.flush()
    version = CommunityVersion(
        community_id=community.id,
        version_number=1,
        name="主案例社区版本 V1",
        status=CommunityVersionStatus.DRAFT,
        map_snapshot={"schema_version": 1, "template": "night_charging_shed_fire"},
    )
    session.add(version)
    session.flush()

    objects = [
        (MapObjectType.BUILDING, "1 号楼", 26, 26, {"floors": 6, "resident_groups": "普通居民"}),
        (MapObjectType.BUILDING, "2 号楼", 46, 24, {"floors": 6, "resident_groups": "普通居民"}),
        (MapObjectType.BUILDING, "3 号楼", 58, 48, {"floors": 6, "resident_groups": "含 2 名独居老人、1 名行动不便人员"}),
        (MapObjectType.BUILDING, "4 号楼", 34, 68, {"floors": 5}),
        (MapObjectType.BUILDING, "5 号楼", 72, 70, {"floors": 5}),
        (MapObjectType.EXIT, "北门疏散出口", 12, 12, {"status": "available"}),
        (MapObjectType.EXIT, "南门疏散出口", 84, 88, {"status": "available"}),
        (MapObjectType.CHARGING_SHED, "3 号楼旁集中充电棚", 66, 43, {"fire_source_candidate": True, "time": "20:15"}),
        (MapObjectType.FIRE_HYDRANT, "东侧消火栓", 79, 47, {"status": "pending_check", "note": "主案例中设为故障事件"}),
        (MapObjectType.FIRE_HYDRANT, "北侧备用消火栓", 30, 14, {"status": "available"}),
        (MapObjectType.MICRO_FIRE_STATION, "微型消防站", 18, 53, {"staff": 4}),
        (MapObjectType.ASSEMBLY_POINT, "北侧集合点", 18, 20, {"capacity": 80}),
        (MapObjectType.ASSEMBLY_POINT, "南侧集合点", 80, 80, {"capacity": 60}),
        (MapObjectType.FIRE_LANE, "南门消防通道", 70, 86, {"status": "restricted", "note": "主案例中存在车辆占用风险"}),
    ]
    for object_type, name, x, y, properties in objects:
        session.add(
            MapObject(
                community_version_id=version.id,
                object_type=object_type,
                name=name,
                geometry={"x": x, "y": y},
                properties=properties,
            )
        )

    nodes = [
        ("北门出口", 12, 12, True), ("北侧路口", 30, 18, False), ("中部路口", 48, 38, False),
        ("3 号楼路口", 58, 54, False), ("充电棚路口", 68, 44, False), ("东侧路口", 80, 48, False),
        ("南侧路口", 66, 78, False), ("南门出口", 84, 88, True),
    ]
    node_by_name: dict[str, RoadNode] = {}
    for name, x, y, is_exit in nodes:
        node = RoadNode(community_version_id=version.id, name=name, x=x, y=y, is_exit=is_exit)
        session.add(node)
        session.flush()
        node_by_name[name] = node

    edges = [
        ("北门主通道", "北门出口", "北侧路口", 4.5, RoadEdgeStatus.OPEN),
        ("西北道路", "北侧路口", "中部路口", 4.0, RoadEdgeStatus.OPEN),
        ("3 号楼北侧道路", "中部路口", "3 号楼路口", 3.5, RoadEdgeStatus.OPEN),
        ("充电棚接近道路", "3 号楼路口", "充电棚路口", 3.0, RoadEdgeStatus.OPEN),
        ("东侧支路", "充电棚路口", "东侧路口", 3.0, RoadEdgeStatus.OPEN),
        ("东南连接道路", "东侧路口", "南侧路口", 4.0, RoadEdgeStatus.OPEN),
        ("南门消防通道", "南侧路口", "南门出口", 3.5, RoadEdgeStatus.RESTRICTED),
        ("中部南向道路", "3 号楼路口", "南侧路口", 4.0, RoadEdgeStatus.OPEN),
        ("西侧回路", "北侧路口", "3 号楼路口", 3.0, RoadEdgeStatus.OPEN),
        ("应急绕行支路", "中部路口", "充电棚路口", 2.8, RoadEdgeStatus.OPEN),
    ]
    for name, start, end, width, edge_status in edges:
        session.add(
            RoadEdge(
                community_version_id=version.id,
                name=name,
                start_node_id=node_by_name[start].id,
                end_node_id=node_by_name[end].id,
                width_meters=width,
                status=edge_status,
            )
        )

    session.commit()
    return get_community_or_none(session, community.id), True  # type: ignore[return-value]
