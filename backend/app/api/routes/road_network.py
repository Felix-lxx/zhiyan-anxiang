from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.auth import AuthenticatedIdentity, get_current_identity
from app.api.routes.map_objects import require_current_version
from app.core.database import get_db
from app.models.domain import RoadEdge, RoadNode
from app.schemas.road_network import (
    ReachabilityCheckRead,
    RoadEdgeCreate,
    RoadEdgeRead,
    RoadEdgeStatusUpdate,
    RoadNetworkRead,
    RoadNodeCreate,
    RoadNodeRead,
    RoadNodeUpdate,
)
from app.services.road_network import (
    calculate_reachability,
    create_edge,
    create_node,
    edge_belongs_to_version,
    list_edges,
    list_nodes,
    node_belongs_to_version,
    update_edge_status,
    update_node,
)


router = APIRouter(prefix="/communities/{community_id}/road-network", tags=["road network"])


def serialize_node(node: RoadNode) -> RoadNodeRead:
    return RoadNodeRead.model_validate(node)


def serialize_edge(edge: RoadEdge) -> RoadEdgeRead:
    return RoadEdgeRead.model_validate(edge)


@router.get("", response_model=RoadNetworkRead)
def get_road_network(community_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> RoadNetworkRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        return RoadNetworkRead(nodes=[serialize_node(node) for node in list_nodes(session, version.id)], edges=[serialize_edge(edge) for edge in list_edges(session, version.id)])
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="道路网络服务暂不可用，请检查 PostgreSQL 连接。") from exc


@router.post("/nodes", response_model=RoadNodeRead, status_code=status.HTTP_201_CREATED)
def post_node(community_id: str, payload: RoadNodeCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> RoadNodeRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        return serialize_node(create_node(session, community_version_id=version.id, **payload.model_dump()))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="道路节点保存失败，请检查数据库连接。") from exc


@router.patch("/nodes/{node_id}", response_model=RoadNodeRead)
def patch_node(community_id: str, node_id: str, payload: RoadNodeUpdate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> RoadNodeRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        node = node_belongs_to_version(session, node_id=node_id, community_version_id=version.id)
        if node is None:
            raise HTTPException(status_code=404, detail="未找到该道路节点。")
        return serialize_node(update_node(session, node, **payload.model_dump()))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="道路节点更新失败，请检查数据库连接。") from exc


@router.post("/edges", response_model=RoadEdgeRead, status_code=status.HTTP_201_CREATED)
def post_edge(community_id: str, payload: RoadEdgeCreate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> RoadEdgeRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        valid_ids = {node.id for node in list_nodes(session, version.id)}
        if payload.start_node_id not in valid_ids or payload.end_node_id not in valid_ids:
            raise HTTPException(status_code=422, detail="道路边的两个端点必须属于当前社区版本。")
        return serialize_edge(create_edge(session, community_version_id=version.id, **payload.model_dump()))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="道路边保存失败，请检查数据库连接。") from exc


@router.patch("/edges/{edge_id}/status", response_model=RoadEdgeRead)
def patch_edge_status(community_id: str, edge_id: str, payload: RoadEdgeStatusUpdate, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> RoadEdgeRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        edge = edge_belongs_to_version(session, edge_id=edge_id, community_version_id=version.id)
        if edge is None:
            raise HTTPException(status_code=404, detail="未找到该道路边。")
        return serialize_edge(update_edge_status(session, edge, payload.status))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="道路状态更新失败，请检查数据库连接。") from exc


@router.get("/reachability", response_model=ReachabilityCheckRead)
def get_reachability(community_id: str, identity: AuthenticatedIdentity = Depends(get_current_identity), session: Session = Depends(get_db)) -> ReachabilityCheckRead:
    try:
        version = require_current_version(session, community_id, identity.username)
        return ReachabilityCheckRead(**calculate_reachability(list_nodes(session, version.id), list_edges(session, version.id)))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="可达性检查暂不可用，请检查数据库连接。") from exc
