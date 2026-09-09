from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import SceneStatus


class SceneTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    description: str
    defaults: dict[str, Any]


class SceneCreate(BaseModel):
    template_id: str
    name: str = Field(min_length=2, max_length=120)


class SceneVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    community_version_id: str
    version_number: int
    status: SceneStatus
    parameters: dict[str, Any]


class SceneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    community_id: str
    template_id: str
    name: str
    status: SceneStatus
    created_at: datetime
    updated_at: datetime
    versions: list[SceneVersionRead]


class ChargingShedParametersUpdate(BaseModel):
    fire_source_object_id: str
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    wind_direction: str = Field(min_length=1, max_length=32)
    resident_count: int = Field(ge=1, le=1000)
    hydrant_status: str = Field(pattern=r"^(available|faulty)$")
    south_lane_status: str = Field(pattern=r"^(open|restricted|blocked)$")
    stair_width: float = Field(default=1.2, ge=0.6, le=3.0)


class SimulationPreviewRead(BaseModel):
    simulation: dict[str, Any] = Field(default_factory=dict)
    minute: int
    fire_level: str
    smoke_level: str
    risk_level: str
    affected_targets: list[str]
    route_advice: str
    explanation: str
