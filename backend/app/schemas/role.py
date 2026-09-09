from pydantic import BaseModel, ConfigDict

from app.models.domain import RoleCode


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: RoleCode
    name: str
    description: str
