import socket
import uuid
from pathlib import Path

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = Path("/run/secrets")

ROLES = ("all", "web", "worker", "poller")
POLL_TTL_MARGIN = 10.0


def _instance_id() -> str:
    return f"{socket.gethostname().split('.')[0]}-{uuid.uuid4().hex[:8]}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        secrets_dir=str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False

    instance_id: str = Field(default_factory=_instance_id, validation_alias="INSTANCE_ID")
    role: str = Field(default="all", validation_alias=AliasChoices("UNSAFIE_ROLE", "ROLE"))

    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "unsafie"
    db_user: str = "unsafie"
    db_password: str = ""

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_max_connections: int = 32
    redis_timeout: float = 5.0
    redis_prefix: str = "unsafie"
    lock_ttl: float = 30.0
    lock_wait: float = 10.0
    lock_retry: float = 0.05

    poll_timeout: int = 20
    poll_lock_ttl: float = 45.0
    poll_claim_interval: float = 10.0
    poll_failure_cooldown: float = 60.0

    job_lease: float = 300.0
    job_lock_ttl: float = 60.0
    chat_lock_ttl: float = 30.0
    chat_lock_wait: float = 60.0
    repo_lock_ttl: float = 120.0
    repo_lock_wait: float = 120.0
    snapshot_lock_ttl: float = 900.0
    snapshot_wait: float = 180.0
    snapshot_refused_ttl: float = 86_400.0
    queue_ttl: float = 86_400.0
    installation_token_ttl: float = 2_900.0
    turn_heartbeat: float = 15.0
    turn_stale_after: float = 90.0
    janitor_interval: float = 30.0
    webhook_batch: int = 20
    webhook_worker_interval: float = 2.0
    webhook_max_attempts: int = 5

    log_level: str = "INFO"
    log_truncate: int = 2000
    sql_echo: bool = False

    service_name: str = Field(
        default="unsafie", validation_alias=AliasChoices("SERVICE_NAME", "OTEL_SERVICE_NAME")
    )
    service_version: str = Field(
        default="", validation_alias=AliasChoices("SERVICE_VERSION", "UNSAFIE_VERSION")
    )
    environment: str = Field(
        default="dev", validation_alias=AliasChoices("ENVIRONMENT", "DEPLOYMENT_ENVIRONMENT")
    )

    otel_enabled: bool = True
    otel_endpoint: str = Field(
        default="http://127.0.0.1:4317",
        validation_alias=AliasChoices("OTEL_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    otel_protocol: str = Field(
        default="grpc",
        validation_alias=AliasChoices("OTEL_PROTOCOL", "OTEL_EXPORTER_OTLP_PROTOCOL"),
    )
    otel_traces_path: str = "/insert/opentelemetry/v1/traces"
    otel_sample_ratio: float = 1.0
    otel_capture_content: bool = False
    otel_max_attr_len: int = 4096
    otel_export_timeout: int = 10
    otel_queue_size: int = 4096
    otel_batch_size: int = 512
    otel_schedule_delay: int = 2000

    claude_model: str = "claude-opus-5"
    chats_dir: Path = Path("chats")
    claude_config_dir: Path = Field(
        default_factory=lambda: Path.home() / ".claude",
        validation_alias="CLAUDE_CONFIG_DIR",
    )
    lineage_depth: int = 500

    public_base_url: str = "https://unsafie.com"
    github_base_url: str = "https://github.unsafie.com"
    share_base_url: str = "https://unsafie.com"
    static_dir: Path = ROOT / "svelte" / "build"

    fluent_dir: Path = ROOT / "fluent"
    default_locale: str = "en"

    admin_token: str = ""
    admin_session_days: int = 30

    github_api_url: str = "https://api.github.com"
    github_repo_sync_limit: int = 200
    github_prompt_repos: int = 60
    github_max_file_bytes: int = 1_048_576
    github_max_changes: int = 200
    github_max_rebase_commits: int = 50
    github_connections: int = 16
    github_concurrency: int = 8
    github_cache_dir: Path = Path("cache")
    github_cache_memory_bytes: int = 67_108_864
    github_cache_item_bytes: int = 4_194_304
    github_cache_disk_bytes: int = 2_147_483_648
    github_cache_sweep_interval: int = 3600
    github_bulk_min_files: int = 8
    github_bulk_max_bytes: int = 104_857_600
    github_bulk_extract_bytes: int = 268_435_456
    github_bulk_file_bytes: int = 4_194_304
    webhook_keep_days: int = 7
    webhook_cleanup_interval: int = 3600

    ssh_connect_timeout: float = 10.0
    ssh_command_timeout: float = 120.0
    ssh_max_command_timeout: float = 900.0
    ssh_idle_timeout: float = 900.0
    ssh_keepalive: float = 15.0
    ssh_max_output: int = 60_000
    ssh_max_file_bytes: int = 5_242_880

    default_timezone: str = "UTC"
    schedule_enabled: bool = True
    schedule_tick: int = 20
    schedule_max_per_chat: int = 50
    schedule_min_interval: int = 300
    watch_min_interval: int = 60
    watch_max_per_chat: int = 30
    watch_command_timeout: float = 30.0

    http_timeout: int = 30
    http_max_timeout: int = 120
    http_max_body: int = 20_971_520

    events_buffer: int = 10_000
    events_queue: int = 4_096
    events_batch: int = 100
    events_block: float = 20.0

    @field_validator(
        "fluent_dir",
        "static_dir",
        "chats_dir",
        "claude_config_dir",
        "github_cache_dir",
        mode="before",
    )
    @classmethod
    def _path(cls, v):
        return Path(v) if isinstance(v, str) else v

    @field_validator("role", mode="before")
    @classmethod
    def _role(cls, v):
        value = str(v or "all").strip().lower()
        if value not in ROLES:
            raise ValueError(f"UNSAFIE_ROLE must be one of {', '.join(ROLES)}, got '{v}'")
        return value

    @model_validator(mode="after")
    def _polling_handover(self):
        if self.poll_lock_ttl <= self.poll_timeout + POLL_TTL_MARGIN:
            raise ValueError(
                f"POLL_LOCK_TTL must exceed POLL_TIMEOUT by more than {POLL_TTL_MARGIN}s: a dead "
                f"instance leaves a getUpdates call hanging for up to POLL_TIMEOUT seconds, and "
                f"the next instance must not start polling before telegram has dropped it "
                f"(got {self.poll_lock_ttl} vs {self.poll_timeout})"
            )
        if self.poll_claim_interval * 3 > self.poll_lock_ttl:
            raise ValueError(
                "POLL_CLAIM_INTERVAL must be at most a third of POLL_LOCK_TTL, so that a lock "
                f"survives two missed renewals (got {self.poll_claim_interval} "
                f"vs {self.poll_lock_ttl})"
            )
        if self.turn_stale_after < self.turn_heartbeat * 3:
            raise ValueError(
                "TURN_STALE_AFTER must be at least three heartbeats, or a running turn is "
                f"reaped while its owner is alive (got {self.turn_stale_after} "
                f"vs {self.turn_heartbeat})"
            )
        return self

    @property
    def runs_web(self) -> bool:
        return self.role in ("all", "web")

    @property
    def runs_worker(self) -> bool:
        return self.role in ("all", "worker")

    @property
    def runs_poller(self) -> bool:
        return self.role in ("all", "poller")

    @computed_field
    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        auth = self.db_user if not self.db_password else f"{self.db_user}:{self.db_password}"
        return f"postgresql+psycopg://{auth}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def share_origin(self) -> str:
        return self.share_base_url.rstrip("/")

    @property
    def public_origin(self) -> str:
        return self.public_base_url.rstrip("/")

    @property
    def github_origin(self) -> str:
        return self.github_base_url.rstrip("/")


settings = Settings()
