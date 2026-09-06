from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from unsafie.database import Base


class CredentialKind(StrEnum):
    API_KEY = "api_key"
    OAUTH = "oauth"


class AnthropicCredential(Base):
    __tablename__ = "anthropic_credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    secret: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    failures: Mapped[int] = mapped_column(default=0, server_default="0")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uses: Mapped[int] = mapped_column(default=0, server_default="0")
    in_flight: Mapped[int] = mapped_column(default=0, server_default="0")
    max_concurrent: Mapped[int] = mapped_column(default=4, server_default="4")
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
