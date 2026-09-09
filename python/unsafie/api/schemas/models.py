from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BotRead(Base):
    id: int
    token_masked: str
    running: bool
    polled_by: str | None = None
    username: str | None = None
    chats: int = 0


class BotWrite(BaseModel):
    token: str


class UserRead(Base):
    id: int
    locale: str | None = None
    timezone: str | None = None
    model: str | None = None
    effort: str | None = None
    git_name: str | None = None
    git_email: str | None = None
    has_ssh_key: bool = False
    github_logins: list[str] = []


class OpalSessionRead(Base):
    id: int
    label: str | None = None
    refresh_token_masked: str
    enabled: bool
    failures: int
    cooldown_until: datetime | None = None
    last_error: str | None = None
    last_used_at: datetime | None = None
    uses: int
    created_at: datetime


class OpalSessionWrite(BaseModel):
    refresh_token: str
    label: str | None = None


class OpalSessionPatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    reset: bool = False


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
    root_id: UUID
    status: str
    credential_id: int | None = None
    num_turns: int
    result: str | None = None
    instance_id: str | None = None
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
    conversation: list[TurnRead] = []
    responses: list[ResponseRead] = []
    messages: int = 0


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


class ArtifactRead(Base):
    id: int
    slug: str
    kind: str
    title: str | None = None
    url: str
    bytes: int = 0
    chat_id: int | None = None
    turn_id: UUID | None = None
    created_at: datetime


class PeriodRead(BaseModel):
    turns: int
    failed: int


class DayPointRead(BaseModel):
    day: str
    turns: int


class OverviewRead(BaseModel):
    users: int
    chats: int
    bots: int
    bots_running: int
    instances: int = 0
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
    history_bytes: int = 0
    github_app: str | None
    day: PeriodRead
    week: PeriodRead
    month: PeriodRead
    daily: list[DayPointRead]


class LoginWrite(BaseModel):
    token: str
