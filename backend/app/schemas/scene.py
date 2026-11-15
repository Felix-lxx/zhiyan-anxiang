from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator, field_serializer

from app.models.domain import SceneStatus


class ScenarioCapabilitiesRead(BaseModel):
    code: str
    contract_version: int
    title: str
    status: Literal["available", "planned", "unsupported"]
    notice: str
    source_types: list[str]
    location_kinds: list[str]
    features: list[str]
    parameter_schema: str | None
    environment_model: str | None
    can_create: bool
    can_configure: bool
    can_preview: bool
    can_publish: bool
    can_run: bool


class SceneTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    code: str
    name: str
    description: str
    defaults: dict[str, Any]

    @computed_field
    @property
    def capabilities(self) -> ScenarioCapabilitiesRead:
        from app.services.scenario_contracts import contract_for
        return ScenarioCapabilitiesRead.model_validate(contract_for(self.code).payload())


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
    capabilities: ScenarioCapabilitiesRead | None = None


class PopulationProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')

    mobility_count: int = Field(ge=0, le=1000, strict=True)
    direct_contact_count: int = Field(ge=0, le=1000, strict=True)
    sleeping_count: int = Field(ge=0, le=1000, strict=True)
    awake_preparation_seconds: int = Field(default=8, ge=0, le=120, strict=True)
    sleeping_preparation_seconds: int = Field(default=25, ge=0, le=180, strict=True)
    walking_speed: float = Field(default=1.25, ge=.8, le=1.8, allow_inf_nan=False, strict=True)
    mobility_walking_speed: float = Field(default=.65, ge=.3, le=1.2, allow_inf_nan=False, strict=True)

    @model_validator(mode='after')
    def coherent_response(self):
        if self.mobility_walking_speed > self.walking_speed:
            raise ValueError('行动受限速度不能高于自主行动速度。')
        if self.sleeping_preparation_seconds < self.awake_preparation_seconds:
            raise ValueError('熟睡准备时间不能短于清醒准备时间。')
        return self


class CommunityTrainingParameters(BaseModel):
    building_release_mode: Literal['shared_corridor', 'assembly_serial'] = 'shared_corridor'
    community_profile: Literal['legacy', 'night_shift'] = 'legacy'
    duty_staff_count: int = Field(default=4, ge=1, le=8)
    simulation_seed: int = Field(default=2026, ge=0, le=2147483647)
    population_profile: PopulationProfile | None = None

    @field_serializer('population_profile')
    def serialize_population_profile(self, value):
        # Preserve defaults within an explicitly supplied profile even when
        # the outer PATCH is serialized with exclude_unset=True.
        return value.model_dump() if value is not None else None

    @model_validator(mode='after')
    def population_limits(self):
        if self.population_profile is None:
            return self
        if self.community_profile != 'night_shift':
            raise ValueError('请先启用社区夜班规则，再配置成员需求。')
        count = getattr(self, 'resident_count', 0)
        for name in ('mobility_count', 'direct_contact_count', 'sleeping_count'):
            if getattr(self.population_profile, name) > count:
                raise ValueError('每项需求人数不能超过参演居民总数；各项可以重叠。')
        return self


class ChargingShedParametersUpdate(CommunityTrainingParameters):
    fire_source_type: Literal['charging_shed'] = 'charging_shed'
    fire_source_object_id: str = Field(min_length=1, max_length=64)
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    wind_direction: str = Field(min_length=1, max_length=32)
    resident_count: int = Field(ge=1, le=1000)
    hydrant_status: str = Field(pattern=r"^(available|faulty)$")
    south_lane_status: str = Field(pattern=r"^(open|restricted|blocked)$")
    stair_width: float = Field(default=1.2, ge=0.6, le=3.0)


class FireSourceCandidateRead(BaseModel):
    id: str
    name: str
    object_type: Literal['charging_shed', 'building']
    floors: int = 1


class KitchenParametersUpdate(CommunityTrainingParameters):
    fire_source_type: Literal['kitchen']
    fire_source_object_id: str = Field(min_length=1, max_length=64)
    fire_floor: int = Field(ge=1, le=20)
    fire_room: Literal['east', 'west']
    room_door_state: Literal['open', 'closed'] = 'open'
    start_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    wind_direction: str = Field(min_length=1, max_length=32)
    resident_count: int = Field(ge=1, le=1000)
    hydrant_status: str = Field(pattern=r"^(available|faulty)$")
    south_lane_status: str = Field(pattern=r"^(open|restricted|blocked)$")
    stair_width: float = Field(default=1.2, ge=0.6, le=3.0)


class SimulationPreviewRead(BaseModel):
    configuration_validation: dict[str, Any] | None = None
    simulation: dict[str, Any] = Field(default_factory=dict)
    minute: int
    fire_level: str
    smoke_level: str
    risk_level: str
    affected_targets: list[str]
    route_advice: str
    explanation: str
