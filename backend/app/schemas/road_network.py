from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.domain import RoadEdgeStatus


class RoadNodeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    is_exit: bool = False


class RoadNodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    is_exit: bool | None = None


class RoadNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_version_id: str
    name: str
    x: float
    y: float
    is_exit: bool
    created_at: datetime
    updated_at: datetime


class RoadEdgeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    start_node_id: str
    end_node_id: str
    width_meters: float = Field(ge=0.5, le=30)
    status: RoadEdgeStatus = RoadEdgeStatus.OPEN

    @model_validator(mode="after")
    def validate_distinct_nodes(self) -> "RoadEdgeCreate":
        if self.start_node_id == self.end_node_id:
            raise ValueError("道路边的起点和终点不能相同。")
        return self


class RoadEdgeStatusUpdate(BaseModel):
    status: RoadEdgeStatus


class RoadEdgeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_version_id: str
    name: str
    start_node_id: str
    end_node_id: str
    width_meters: float
    status: RoadEdgeStatus
    created_at: datetime
    updated_at: datetime


class RoadNetworkRead(BaseModel):
    nodes: list[RoadNodeRead]
    edges: list[RoadEdgeRead]


class ReachabilityCheckRead(BaseModel):
    status: str
    summary: str
    total_nodes: int
    reachable_nodes: int
    exit_node_count: int
    blocked_edge_count: int
    unreachable_node_ids: list[str]
    issues: list[str]
