from datetime import UTC, datetime
from uuid import uuid4
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
class DecisionTask(Base):
    __tablename__='decision_tasks'
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid4()))
    decision_point_id:Mapped[str]=mapped_column(ForeignKey('decision_points.id',ondelete='CASCADE'),nullable=False)
    scene_version_id:Mapped[str]=mapped_column(ForeignKey('scene_versions.id',ondelete='CASCADE'),nullable=False)
    title:Mapped[str]=mapped_column(String(160),nullable=False)
    target:Mapped[str]=mapped_column(String(160),nullable=False)
    deadline_seconds:Mapped[int]=mapped_column(Integer,nullable=False)
    status:Mapped[str]=mapped_column(String(32),default='pending',nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(UTC),nullable=False)
