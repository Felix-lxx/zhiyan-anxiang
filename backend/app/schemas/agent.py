from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    goal: str = Field(min_length=2, max_length=2000)
    building_id: str | None = Field(default=None, max_length=64)
    resident_ids: list[str] = Field(default_factory=list, max_length=1000)
    priority_assist: bool = True
    robot_broadcast: bool = False
    use_model: bool = False

    @field_validator("goal")
    @classmethod
    def meaningful(cls, value):
        if not value.strip(): raise ValueError("请输入训练目标")
        return value.strip()


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    candidate_id: str | None = Field(default=None, max_length=40)
    action: Literal["approve", "stop", "replan", "review"]


class GoalInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_id: str | None
    exit_preference: Literal["balanced", "north", "south"]
    priority_assist: bool
