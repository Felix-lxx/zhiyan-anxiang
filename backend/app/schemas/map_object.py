from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import MapObjectType


class MapPoint(BaseModel):
    """在二维社区底图上的归一化定位点，坐标范围为 0 到 100。"""

    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)


class MapObjectCreate(BaseModel):
    object_type: MapObjectType
    name: str = Field(min_length=2, max_length=120)
    geometry: MapPoint
    properties: dict[str, Any] = Field(default_factory=dict)


class MapObjectUpdate(BaseModel):
    object_type: MapObjectType | None = None
    name: str | None = Field(default=None, min_length=2, max_length=120)
    geometry: MapPoint | None = None
    properties: dict[str, Any] | None = None


class MapObjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    community_version_id: str
    object_type: MapObjectType
    name: str
    geometry: MapPoint
    properties: dict[str, Any]
    created_at: datetime
    updated_at: datetime
