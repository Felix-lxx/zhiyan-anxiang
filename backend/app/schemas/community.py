from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.domain import CommunityStatus, CommunityVersionStatus


class CommunityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=120)
    address: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CommunityUpdate(CommunityCreate):
    expected_updated_at: datetime


class CommunityVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    name: str
    status: CommunityVersionStatus


class CommunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    address: str | None
    description: str | None
    status: CommunityStatus
    created_at: datetime
    updated_at: datetime
    owner_username: str
    versions: list[CommunityVersionSummary]
