from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RoleCode(str, Enum):
    SYSTEM_ADMIN = "system_admin"
    EXERCISE_DESIGNER = "exercise_designer"
    DRILL_DIRECTOR = "drill_director"
    COMMANDER = "commander"
    PROPERTY_STAFF = "property_staff"
    RESIDENT_REPRESENTATIVE = "resident_representative"
    ASSESSOR = "assessor"


class CommunityStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CommunityVersionStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class MapObjectType(str, Enum):
    BUILDING = "building"
    ROAD = "road"
    FIRE_LANE = "fire_lane"
    EXIT = "exit"
    ASSEMBLY_POINT = "assembly_point"
    FIRE_HYDRANT = "fire_hydrant"
    CHARGING_SHED = "charging_shed"
    MICRO_FIRE_STATION = "micro_fire_station"


class RoadEdgeStatus(str, Enum):
    OPEN = "open"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"


class SceneStatus(str, Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[RoleCode] = mapped_column(SqlEnum(RoleCode), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    users: Mapped[list[UserRole]] = relationship(back_populates="role", cascade="all, delete-orphan")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    roles: Mapped[list[UserRole]] = relationship(back_populates="user", cascade="all, delete-orphan")
    owned_communities: Mapped[list[Community]] = relationship(back_populates="owner")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)

    user: Mapped[User] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="users")


class Community(TimestampMixin, Base):
    __tablename__ = "communities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CommunityStatus] = mapped_column(
        SqlEnum(CommunityStatus), default=CommunityStatus.DRAFT, nullable=False
    )
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    owner: Mapped[User] = relationship(back_populates="owned_communities")
    versions: Mapped[list[CommunityVersion]] = relationship(
        back_populates="community", cascade="all, delete-orphan", order_by="CommunityVersion.version_number"
    )


class CommunityVersion(TimestampMixin, Base):
    __tablename__ = "community_versions"
    __table_args__ = (UniqueConstraint("community_id", "version_number", name="uq_community_version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_id: Mapped[str] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[CommunityVersionStatus] = mapped_column(
        SqlEnum(CommunityVersionStatus), default=CommunityVersionStatus.DRAFT, nullable=False
    )
    map_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    community: Mapped[Community] = relationship(back_populates="versions")
    map_objects: Mapped[list[MapObject]] = relationship(
        back_populates="community_version", cascade="all, delete-orphan"
    )
    road_nodes: Mapped[list[RoadNode]] = relationship(
        back_populates="community_version", cascade="all, delete-orphan"
    )


class MapObject(TimestampMixin, Base):
    __tablename__ = "map_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_version_id: Mapped[str] = mapped_column(
        ForeignKey("community_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[MapObjectType] = mapped_column(SqlEnum(MapObjectType), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    geometry: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    community_version: Mapped[CommunityVersion] = relationship(back_populates="map_objects")


class RoadNode(TimestampMixin, Base):
    __tablename__ = "road_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_version_id: Mapped[str] = mapped_column(
        ForeignKey("community_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    x: Mapped[float] = mapped_column(nullable=False)
    y: Mapped[float] = mapped_column(nullable=False)
    is_exit: Mapped[bool] = mapped_column(default=False, nullable=False)

    community_version: Mapped[CommunityVersion] = relationship(back_populates="road_nodes")
    outgoing_edges: Mapped[list[RoadEdge]] = relationship(
        back_populates="start_node", foreign_keys="RoadEdge.start_node_id", cascade="all, delete-orphan"
    )
    incoming_edges: Mapped[list[RoadEdge]] = relationship(
        back_populates="end_node", foreign_keys="RoadEdge.end_node_id", cascade="all, delete-orphan"
    )


class RoadEdge(TimestampMixin, Base):
    __tablename__ = "road_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_version_id: Mapped[str] = mapped_column(
        ForeignKey("community_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_node_id: Mapped[str] = mapped_column(ForeignKey("road_nodes.id", ondelete="CASCADE"), nullable=False)
    end_node_id: Mapped[str] = mapped_column(ForeignKey("road_nodes.id", ondelete="CASCADE"), nullable=False)
    width_meters: Mapped[float] = mapped_column(nullable=False, default=4.0)
    status: Mapped[RoadEdgeStatus] = mapped_column(SqlEnum(RoadEdgeStatus), nullable=False, default=RoadEdgeStatus.OPEN)

    start_node: Mapped[RoadNode] = relationship(back_populates="outgoing_edges", foreign_keys=[start_node_id])
    end_node: Mapped[RoadNode] = relationship(back_populates="incoming_edges", foreign_keys=[end_node_id])


class SceneTemplate(TimestampMixin, Base):
    __tablename__ = "scene_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Scene(TimestampMixin, Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    community_id: Mapped[str] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id: Mapped[str] = mapped_column(ForeignKey("scene_templates.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[SceneStatus] = mapped_column(SqlEnum(SceneStatus), default=SceneStatus.DRAFT, nullable=False)

    template: Mapped[SceneTemplate] = relationship()
    versions: Mapped[list[SceneVersion]] = relationship(back_populates="scene", cascade="all, delete-orphan", order_by="SceneVersion.version_number")


class SceneVersion(TimestampMixin, Base):
    __tablename__ = "scene_versions"
    __table_args__ = (UniqueConstraint("scene_id", "version_number", name="uq_scene_version_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), nullable=False)
    community_version_id: Mapped[str] = mapped_column(ForeignKey("community_versions.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SceneStatus] = mapped_column(SqlEnum(SceneStatus), default=SceneStatus.DRAFT, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    scene: Mapped[Scene] = relationship(back_populates="versions")
    community_version: Mapped[CommunityVersion] = relationship()
    decision_points: Mapped[list[DecisionPoint]] = relationship(back_populates="scene_version", cascade="all, delete-orphan")


class DecisionPoint(TimestampMixin, Base):
    __tablename__ = "decision_points"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    scene_version_id: Mapped[str] = mapped_column(ForeignKey("scene_versions.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger_condition: Mapped[str] = mapped_column(String(255), nullable=False)
    responsible_role: Mapped[str] = mapped_column(String(64), nullable=False)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_version: Mapped[SceneVersion] = relationship(back_populates="decision_points")
    options: Mapped[list[DecisionOption]] = relationship(
        back_populates="decision_point",
        foreign_keys="DecisionOption.decision_point_id",
        cascade="all, delete-orphan",
    )


class DecisionOption(TimestampMixin, Base):
    __tablename__ = "decision_options"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    decision_point_id: Mapped[str] = mapped_column(ForeignKey("decision_points.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    consequence: Mapped[str] = mapped_column(String(500), nullable=False)
    next_decision_point_id: Mapped[str | None] = mapped_column(ForeignKey("decision_points.id"), nullable=True)
    decision_point: Mapped[DecisionPoint] = relationship(back_populates="options", foreign_keys=[decision_point_id])
