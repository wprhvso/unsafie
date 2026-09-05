from datetime import datetime

from pydantic import BaseModel, Field

from yet_another_claude_bot.models.credential import CredentialKind


class CredentialCreate(BaseModel):
    kind: CredentialKind
    secret: str = Field(min_length=8)
    label: str | None = Field(default=None, max_length=64)


class CredentialUpdate(BaseModel):
    enabled: bool | None = None
    label: str | None = Field(default=None, max_length=64)
    reset: bool = False  # сбросить failures/cooldown


class CredentialRead(BaseModel):
    id: int
    kind: CredentialKind
    secret: str  # маскированный
    label: str | None
    enabled: bool
    failures: int
    cooldown_until: datetime | None
    last_error: str | None
    last_used_at: datetime | None
    uses: int
    total_cost_usd: float
    created_at: datetime
