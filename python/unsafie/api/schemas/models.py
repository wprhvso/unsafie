from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BotRead(Base):
    id: int
    token_masked: str
    running: bool
    username: str | None = None
    chats: int = 0


class BotWrite(BaseModel):
    token: str


class UserRead(Base):
    id: int
    balance: int
    budget: int
    locale: str | None = None
    timezone: str | None = None
    model: str | None = None
    effort: str | None = None
    git_name: str | None = None
    git_email: str | None = None
    has_ssh_key: bool = False
    github_logins: list[str] = []


class TransactionRead(Base):
    id: int
    amount: int
    kind: str
    created_at: datetime


class DepositWrite(BaseModel):
    amount: int


class BudgetWrite(BaseModel):
    budget: int


class CredentialRead(Base):
    id: int
    kind: str
    label: str | None = None
    secret_masked: str
    enabled: bool
    failures: int
    cooldown_until: datetime | None = None
    last_error: str | None = None
    last_used_at: datetime | None = None
    uses: int
    total_cost_usd: float
    created_at: datetime


class CredentialWrite(BaseModel):
    kind: str
    secret: str
    label: str | None = None


class CredentialPatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    reset: bool = False


class ConfigRead(Base):
    ratio: float
    oauth_ratio: float


class ConfigWrite(BaseModel):
    ratio: float | None = None
    oauth_ratio: float | None = None


class ChatRead(Base):
    id: int
    bot_id: int
    chat_id: int
    type: str
    title: str | None = None
    username: str | None = None
    first_seen: datetime
    last_seen: datetime


class MessageRead(BaseModel):
    who: str
    message_id: int | None
    user_id: int | None
    name: str | None
    ts: int
    body: str
    reply_to: int | None = None


class TurnRead(Base):
    id: UUID
    bot_id: int
    chat_id: int
    user_id: int
    parent_id: UUID | None = None
    session_id: str | None = None
    forked: bool
    status: str
    credential_id: int | None = None
    cost_usd: float | None = None
    charge: int
    num_turns: int
    result: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class ResponseRead(Base):
    id: UUID
    kind: str
    content: str
    message_ids: list[int]
    reply_to: int | None = None
    created_at: datetime


class TurnDetail(BaseModel):
    turn: TurnRead
    parent: TurnRead | None = None
    children: list[TurnRead] = []
    responses: list[ResponseRead] = []


class GithubAppRead(Base):
    app_id: int
    slug: str
    name: str
    html_url: str
    created_at: datetime


class GithubAccountRead(Base):
    id: int
    user_id: int
    github_id: int
    login: str
    has_token: bool = False
    scopes: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None


class InstallationRead(Base):
    id: int
    account_login: str
    account_type: str
    repository_selection: str
    suspended: bool
    created_at: datetime


class RepoRead(Base):
    id: int
    installation_id: int | None = None
    owner: str
    name: str
    default_branch: str
    private: bool


class WorktreeRead(Base):
    id: int
    repo_id: int
    repo: str
    branch: str
    base_commit_sha: str
    changes: int
    stashed: int
    updated_at: datetime


class SubscriptionRead(Base):
    id: int
    bot_id: int
    chat_id: int
    user_id: int
    repo: str
    kind: str
    filters: dict
    created_at: datetime


class DeliveryRead(Base):
    delivery_id: str
    event: str
    action: str | None = None
    installation_id: int | None = None
    repo_full_name: str | None = None
    sender: str | None = None
    received_at: datetime
    processed_at: datetime | None = None
    notified: int
    error: str | None = None


class DeliveryDetail(DeliveryRead):
    payload: dict


class ScheduleRead(Base):
    id: int
    bot_id: int
    chat_id: int
    user_id: int
    kind: str
    text: str
    tz: str
    cron: str | None = None
    interval_sec: int | None = None
    next_run_at: datetime
    last_run_at: datetime | None = None
    runs: int
    enabled: bool


class WatchRead(Base):
    id: int
    bot_id: int
    chat_id: int
    user_id: int
    host: str
    name: str
    command: str
    condition: str
    interval_sec: int
    mode: str
    alerting: bool
    fails: int
    last_exit: int | None = None
    last_run_at: datetime | None = None
    next_run_at: datetime
    enabled: bool


class SshHostRead(Base):
    id: int
    user_id: int
    alias: str
    host: str
    port: int
    username: str
    fingerprint: str | None = None
    created_at: datetime
    last_used_at: datetime | None = None
    connected: bool = False


class ShareRead(Base):
    id: int
    slug: str
    response_id: UUID
    url: str
    created_at: datetime


class PeriodRead(BaseModel):
    turns: int
    failed: int
    cost_usd: float
    charge: int


class DayPointRead(BaseModel):
    day: str
    turns: int
    cost_usd: float
    charge: int


class OverviewRead(BaseModel):
    users: int
    chats: int
    bots: int
    bots_running: int
    running_turns: int
    credentials: int
    credentials_total: int
    repos: int
    installations: int
    subscriptions: int
    schedules: int
    watches: int
    watches_alerting: int
    ssh_hosts: int
    ssh_connections: int
    deliveries_pending: int
    deliveries_failed: int
    github_app: str | None
    day: PeriodRead
    week: PeriodRead
    month: PeriodRead
    daily: list[DayPointRead]


class LoginWrite(BaseModel):
    token: str
