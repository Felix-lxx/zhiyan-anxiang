from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoalCreate(BaseModel):
    pause_for_review: bool = False
    include_case_tasks: bool = False
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    goal: str = Field(min_length=2, max_length=2000)
    building_id: str | None = Field(default=None, max_length=64)
    resident_ids: list[str] = Field(default_factory=list, max_length=1000)
    priority_assist: bool = True
    robot_broadcast: bool = False
    use_model: bool = False
    floors: list[int] = Field(default_factory=list, max_length=30)
    objective: Literal['balanced', 'low_exposure', 'fast_arrival'] = 'balanced'
    forbidden_exits: list[Literal['north', 'south']] = Field(default_factory=list, max_length=2)

    @field_validator('floors')
    @classmethod
    def valid_floors(cls, value):
        if any(floor < 1 or floor > 100 for floor in value):
            raise ValueError('楼层应为 1–100 的整数。')
        return sorted(set(value))

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
    use_model: bool = False
    objective: Literal['balanced', 'low_exposure', 'fast_arrival'] | None = None
    forbidden_exits: list[Literal['north', 'south']] | None = Field(default=None, max_length=2)

    @model_validator(mode='after')
    def revision_only(self):
        if self.action != 'replan' and (self.use_model or self.objective is not None or self.forbidden_exits is not None):
            raise ValueError('修订约束和模型授权仅能用于重新比较，不能随批准请求修改方案。')
        if self.forbidden_exits is not None and len(set(self.forbidden_exits)) == 2:
            raise ValueError('两个出口不能同时禁止使用，请先处理通道。')
        return self


class GoalInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    building_id: str | None
    exit_preference: Literal["balanced", "north", "south"]
    priority_assist: bool
