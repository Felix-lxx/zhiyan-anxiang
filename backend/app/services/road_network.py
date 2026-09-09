from collections import deque

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import RoadEdge, RoadEdgeStatus, RoadNode


def list_nodes(session: Session, community_version_id: str) -> list[RoadNode]:
    return list(
        session.scalars(
            select(RoadNode).where(RoadNode.community_version_id == community_version_id).order_by(RoadNode.created_at.asc())
        )
    )


def list_edges(session: Session, community_version_id: str) -> list[RoadEdge]:
    return list(
        session.scalars(
            select(RoadEdge).where(RoadEdge.community_version_id == community_version_id).order_by(RoadEdge.created_at.asc())
        )
    )


def create_node(session: Session, *, community_version_id: str, name: str, x: float, y: float, is_exit: bool) -> RoadNode:
    node = RoadNode(community_version_id=community_version_id, name=name, x=x, y=y, is_exit=is_exit)
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def node_belongs_to_version(session: Session, *, node_id: str, community_version_id: str) -> RoadNode | None:
    return session.scalar(
        select(RoadNode).where(RoadNode.id == node_id, RoadNode.community_version_id == community_version_id)
    )


def update_node(
    session: Session,
    node: RoadNode,
    *,
    name: str | None = None,
    x: float | None = None,
    y: float | None = None,
    is_exit: bool | None = None,
) -> RoadNode:
    if name is not None:
        node.name = name
    if x is not None:
        node.x = x
    if y is not None:
        node.y = y
    if is_exit is not None:
        node.is_exit = is_exit
    session.commit()
    session.refresh(node)
    return node


def create_edge(
    session: Session,
    *,
    community_version_id: str,
    name: str,
    start_node_id: str,
    end_node_id: str,
    width_meters: float,
    status: RoadEdgeStatus,
) -> RoadEdge:
    edge = RoadEdge(
        community_version_id=community_version_id,
        name=name,
        start_node_id=start_node_id,
        end_node_id=end_node_id,
        width_meters=width_meters,
        status=status,
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


def edge_belongs_to_version(session: Session, *, edge_id: str, community_version_id: str) -> RoadEdge | None:
    return session.scalar(
        select(RoadEdge).where(RoadEdge.id == edge_id, RoadEdge.community_version_id == community_version_id)
    )


def update_edge_status(session: Session, edge: RoadEdge, status: RoadEdgeStatus) -> RoadEdge:
    edge.status = status
    session.commit()
    session.refresh(edge)
    return edge


def calculate_reachability(nodes: list[RoadNode], edges: list[RoadEdge]) -> dict:
    exit_ids = {node.id for node in nodes if node.is_exit}
    adjacency: dict[str, set[str]] = {node.id: set() for node in nodes}
    blocked_edge_count = 0
    for edge in edges:
        if edge.status == RoadEdgeStatus.BLOCKED:
            blocked_edge_count += 1
            continue
        adjacency[edge.start_node_id].add(edge.end_node_id)
        adjacency[edge.end_node_id].add(edge.start_node_id)

    reachable = set(exit_ids)
    queue = deque(exit_ids)
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in reachable:
                reachable.add(neighbor)
                queue.append(neighbor)

    unreachable = [node.id for node in nodes if node.id not in reachable]
    issues: list[str] = []
    if not nodes:
        issues.append("尚未登记道路节点，无法判断通道可达性。")
    if not exit_ids:
        issues.append("未标记任何疏散出口节点，无法形成安全撤离终点。")
    if unreachable and exit_ids:
        issues.append(f"有 {len(unreachable)} 个节点无法经当前可通行道路抵达出口。")
    if blocked_edge_count:
        issues.append(f"有 {blocked_edge_count} 条道路边处于阻断状态，已从可达性计算中排除。")

    if not issues:
        status = "passed"
        summary = "所有道路节点均可经当前通行网络抵达出口。"
    elif exit_ids and not unreachable:
        status = "warning"
        summary = "出口仍可到达，但存在被阻断道路边，需在演练前复核。"
    else:
        status = "failed"
        summary = "当前道路网络未通过基础可达性检查。"
    return {
        "status": status,
        "summary": summary,
        "total_nodes": len(nodes),
        "reachable_nodes": len(reachable),
        "exit_node_count": len(exit_ids),
        "blocked_edge_count": blocked_edge_count,
        "unreachable_node_ids": unreachable,
        "issues": issues,
    }
