from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.domain import TimestampMixin


class AccountPreferences(TimestampMixin, Base):
    """Additive table: never changes existing credentials or role assignments."""
    __tablename__ = "account_preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    organization: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    preferences: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
