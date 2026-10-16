from typing import Any, Literal

from pydantic import BaseModel, Field


class DrillCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    time_scale: float = Field(default=1.0, ge=0.5, le=4.0)


class DrillAction(BaseModel):
    action: str = Field(pattern=r"^(start|pause|resume|end)$")


class EventInject(BaseModel):
    resident_id: str | None = Field(default=None, max_length=64)
    event_type: str = Field(pattern=r"^(channel_blocked|hydrant_failure|resident_missing)$")
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    target: str | None = Field(default=None, max_length=120)
    road_edge_id: str | None = Field(default=None, max_length=36)


class RobotCommand(BaseModel):
    command: str = Field(pattern=r"^(step|broadcast|replan|move|cancel)$")
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    target: str | None = Field(default=None, max_length=120)
    task_id: str | None = Field(default=None, max_length=36)


class VehicleCommand(BaseModel):
    command: Literal["dispatch", "cancel", "replan"] = "dispatch"
    vehicle_id: Literal["firetruck-1", "ambulance-1"]
    target_node_id: str | None = Field(default=None, max_length=64)


class ResidentCommand(BaseModel):
    resident_ids: list[str] = Field(min_length=1, max_length=1000)
    exit: str = Field(pattern=r"^(north|south)$")
    action: str = Field(default="evacuate", pattern=r"^(evacuate|priority_assist)$")


class ParticipantAction(BaseModel):
    role: str = Field(min_length=2, max_length=64)
    action: str = Field(pattern=r"^(acknowledge|arrived|resource_ready|resident_counted|report)$")
    message: str = Field(min_length=2, max_length=240)
    task_id: str | None = Field(default=None, max_length=36)
    resident_ids: list[str] = Field(default_factory=list, max_length=1000)
    participant_token: str | None = Field(default=None, max_length=128)


class ParticipantJoin(BaseModel):
    role: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=2, max_length=40)


class ParticipantHeartbeat(BaseModel):
    participant_token: str = Field(min_length=16, max_length=128)


class TaskAction(BaseModel):
    action: str = Field(pattern=r"^(accept|arrive|submit)$")
    evidence: str = Field(default="", max_length=500)
    participant_token: str | None = Field(default=None, max_length=128)


class TaskAssignment(BaseModel):
    participant_id: str = Field(min_length=1, max_length=64)


class DirectorConfig(BaseModel):
    enabled: bool


class BranchCompareRequest(BaseModel):
    at_seconds: int | None = Field(default=None, ge=0)
    baseline_strategy: str = Field(default="south_standard", pattern=r"^(south_standard|north_priority|dual_exit)$")
    alternative_strategy: str = Field(default="north_priority", pattern=r"^(south_standard|north_priority|dual_exit)$")


class EditableBranchCreate(BaseModel):
    at_seconds: int = Field(ge=0)
    before_sequence: int | None = Field(default=None, ge=1)
    name: str = Field(default="另一种选择", min_length=2, max_length=120)


class SearchAssignment(BaseModel):
    resident_id: str = Field(min_length=1, max_length=64)
    responsible: str = Field(min_length=2, max_length=40)


class LiveCommand(BaseModel):
    command_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["state", "event.inject", "road.reopen", "residents.assign", "robot.command", "vehicle.command", "search.assign", "participant.feedback", "task.assign", "task.action", "director.configure"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    target_id: str | None = Field(default=None, max_length=64)
    expected_sequence: int | None = Field(default=None, ge=0)
