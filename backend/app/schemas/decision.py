from pydantic import BaseModel, ConfigDict, Field

class DecisionOptionCreate(BaseModel):
    label: str = Field(min_length=2, max_length=160)
    consequence: str = Field(min_length=2, max_length=500)

class DecisionPointCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    trigger_condition: str = Field(min_length=2, max_length=255)
    responsible_role: str = Field(min_length=2, max_length=64)
    time_limit_seconds: int = Field(ge=5, le=600)
    options: list[DecisionOptionCreate] = Field(min_length=2, max_length=6)

class DecisionOptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; label: str; consequence: str; next_decision_point_id: str | None

class DecisionPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str; name: str; trigger_condition: str; responsible_role: str; time_limit_seconds: int; options: list[DecisionOptionRead]
