import structlog
import socket
import uuid
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = Path("/run/secrets")

ROLES = ("all", "web", "worker", "poller")
CACHE_TTLS = ("5m", "1h")

SafetyThreshold = Literal[
    "BLOCK_LOW_AND_ABOVE",
    "BLOCK_MEDIUM_AND_ABOVE",
    "BLOCK_NONE",
    "BLOCK_ONLY_HIGH",
    "OFF",
]
ThinkingLevel = Literal["LOW", "MEDIUM", "HIGH"]


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
    db_pool_size: int = 20
    db_max_overflow: int = 30
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True

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
    telegram_webhook_secret: str = ""
    telegram_webhook_base_url: str = ""
    telegram_webhook_sync_interval: float = 60.0

    job_lease: float = 300.0
    chat_lock_ttl: float = 30.0
    chat_lock_wait: float = 60.0
    repo_lock_ttl: float = 120.0
    repo_lock_wait: float = 120.0
    snapshot_lock_ttl: float = 900.0
    snapshot_wait: float = 180.0
    snapshot_refused_ttl: float = 86_400.0
    queue_ttl: float = 86_400.0
    installation_token_ttl: float = 2_900.0
    history_max_bytes: int = 33_554_432
    history_keep_days: int = 30
    lineage_depth: int = 500
    shutdown_grace: float = 90.0
    presence_interval: float = 10.0
    turn_heartbeat: float = 15.0
    turn_stale_after: float = 90.0
    janitor_interval: float = 30.0
    webhook_batch: int = 20
    webhook_worker_interval: float = 2.0
    webhook_max_attempts: int = 5
    webhook_keep_days: int = 7

    log_level: str = "INFO"
    log_truncate: int = 2000
    log_format: str = "json"
    sql_echo: bool = False

    service_name: str = Field(
        default="unsafie",
        validation_alias=AliasChoices("SERVICE_NAME", "OTEL_SERVICE_NAME"),
    )
    service_version: str = Field(
        default="",
        validation_alias=AliasChoices("SERVICE_VERSION", "UNSAFIE_VERSION"),
    )
    environment: str = Field(
        default="dev",
        validation_alias=AliasChoices("ENVIRONMENT", "DEPLOYMENT_ENVIRONMENT"),
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
    victoriatraces_url: str = Field(
        default="http://127.0.0.1:10428",
        validation_alias=AliasChoices("VICTORIATRACES_URL", "TRACES_URL"),
    )
    victorialogs_url: str = Field(
        default="http://127.0.0.1:9428",
        validation_alias=AliasChoices("VICTORIALOGS_URL", "LOGS_URL"),
    )
    otel_traces_path: str = "/insert/opentelemetry/v1/traces"
    otel_sample_ratio: float = 1.0
    otel_capture_content: bool = False
    otel_max_attr_len: int = 4096
    otel_export_timeout: int = 10
    otel_queue_size: int = 4096
    otel_batch_size: int = 512
    otel_schedule_delay: int = 2000

    gemini_model: str = "gemini-flash-latest"
    gemini_api_url: str = "https://appcatalyst.pa.googleapis.com/v1beta1/models"
    gemini_safety_threshold: SafetyThreshold = "BLOCK_NONE"
    gemini_thinking_level: ThinkingLevel = "HIGH"
    gemini_max_output_tokens: int = 65536
    gemini_timeout: float = 900.0
    gemini_connect_timeout: float = 20.0
    gemini_read_timeout: float = 180.0
    gemini_retries: int = 30
    gemini_connections: int = 16

    opal_refresh_url: str = "https://opal.google/connection/refresh"
    opal_access_ttl: int = 2700
    opal_pick_attempts: int = 30

    cache_ttl: str = "1h"
    agent_max_steps: int = 6400
    agent_block_timeout: float = 900.0

    public_base_url: str = "https://unsafie.com"
    github_base_url: str = "https://github.unsafie.com"
    artifact_base_url: str = Field(
        default="https://unsafie.com",
        validation_alias=AliasChoices("ARTIFACT_BASE_URL", "SHARE_BASE_URL"),
    )
    static_dir: Path = ROOT / "svelte" / "build"

    fluent_dir: Path = ROOT / "fluent"
    default_locale: str = "en"

    admin_token: str = ""
    admin_session_days: int = 30

    chats_dir: Path = Field(default=ROOT / "chats", validation_alias=AliasChoices("CHATS_DIR"))

    github_api_url: str = "https://api.github.com"
    github_repo_sync_limit: int = 200
    github_prompt_repos: int = 60
    github_max_file_bytes: int = 1_048_576
    github_max_changes: int = 200
    github_max_rebase_commits: int = 50
    github_inline_bytes: int = 131_072
    github_inline_total_bytes: int = 4_194_304
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

    ssh_connect_timeout: float = 10.0
    ssh_command_timeout: float = 120.0
    ssh_max_command_timeout: float = 900.0
    ssh_idle_timeout: float = 900.0
    ssh_keepalive: float = 15.0
    ssh_max_output: int = 60_000
    ssh_max_file_bytes: int = 5_242_880

    pool_enabled: bool = False
    pool_blob_dir: Path = ROOT / "pool-blobs"
    pool_machine_ttl: float = 90.0
    pool_poll_timeout: float = 25.0
    pool_heartbeat: float = 20.0
    pool_take_wait: float = 180.0
    pool_lease_idle: float = 900.0
    pool_hold_max: float = 3_600.0
    pool_command_timeout: float = 600.0
    pool_block_timeout: float = 900.0
    pool_max_command_timeout: float = 21600.0
    pool_max_output: int = 4_000_000
    pool_max_output_lines: int = 4_000_000
    pool_output_ttl: float = 3600.0
    pool_job_ttl: float = 19_800.0
    pool_keeper_interval: float = 30.0
    pool_launch_burst: int = 10
    pool_workflow: str = "unsafie.yml"
    pool_repo_name: str = "unsafie-pool"
    pool_sdk_spec: str = "git+https://github.com/wprhvso/unsafie@main#subdirectory=python"
    pool_wire_spec: str = (
        "git+https://github.com/wprhvso/unsafie@main#subdirectory=python/unsafie-wire"
    )
    pool_max_blob_bytes: int = 536_870_912
    pool_max_blob_item: int = 134_217_728
    pool_boot_grace: float = 900.0
    pool_cache_url: str = ""
    pool_vnc_port: int = 5900
    pool_desktop_ttl: float = 7_200.0
    pool_tunnel_wait: float = 30.0
    pool_ci_enabled: bool = False
    pool_ci_interval: float = 30.0
    pool_ci_jobs: int = 5
    pool_ci_max_jobs: int = 20
    pool_ci_idle: int = 300
    pool_ci_lifetime: int = 3600
    pool_ci_reserve: int = 2

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

    live_enabled: bool = True
    live_ttl: float = 86_400.0
    live_buffer: int = 20_000
    live_queue: int = 16_384
    live_batch: int = 200
    live_block: float = 20.0
    live_flush: float = 0.1
    live_max_text: int = 65_536
    live_max_bytes: int = 33_554_432
    live_images: bool = True
    live_image_bytes: int = 262_144
    live_stream_seconds: float = 3_600.0

    @field_validator("fluent_dir", "static_dir", "github_cache_dir", "pool_blob_dir", "chats_dir", mode="before")
    @classmethod
    def _path(cls, v):
        return Path(v) if isinstance(v, str) else v

    @field_validator("role", mode="before")
    @classmethod
    def _role(cls, v):
        value = str(v or "all").strip().lower()
        if value not in ROLES:
            msg = f"UNSAFIE_ROLE must be one of {', '.join(ROLES)}, got '{v}'"
            raise ValueError(msg)
        return value

    @field_validator("cache_ttl", mode="before")
    @classmethod
    def _cache_ttl(cls, v):
        value = str(v or "1h").strip().lower()
        if value not in CACHE_TTLS:
            msg = f"CACHE_TTL must be one of {', '.join(CACHE_TTLS)}, got '{v}'"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _turn_stale(self):
        if self.turn_stale_after < self.turn_heartbeat * 3:
            msg = (
                "TURN_STALE_AFTER must be at least three heartbeats, or a running turn is "
                f"reaped while its owner is alive (got {self.turn_stale_after} "
                f"vs {self.turn_heartbeat})"
            )
            raise ValueError(
                msg,
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
        return self.role in ("all", "poller", "web")

    @computed_field
    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        auth = self.db_user if not self.db_password else f"{self.db_user}:{self.db_password}"
        return f"postgresql+psycopg://{auth}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def artifact_origin(self) -> str:
        return self.artifact_base_url.rstrip("/")

    @property
    def public_origin(self) -> str:
        return self.public_base_url.rstrip("/")

    @property
    def github_origin(self) -> str:
        return self.github_base_url.rstrip("/")


settings = Settings()
