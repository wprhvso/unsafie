from pathlib import Path

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = Path("/run/secrets")


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

    database_url_override: str | None = Field(default=None, validation_alias="DATABASE_URL")
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "unsafie"
    db_user: str = "unsafie"
    db_password: str = ""

    log_level: str = "INFO"
    log_truncate: int = 2000
    sql_echo: bool = False

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
    github_max_file_bytes: int = 1_048_576
    github_max_changes: int = 200
    github_max_rebase_commits: int = 50
    github_connections: int = 16
    github_concurrency: int = 8
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

    events_buffer: int = 1000
    events_queue: int = 256

    @field_validator("fluent_dir", "static_dir", "chats_dir", "claude_config_dir", mode="before")
    @classmethod
    def _path(cls, v):
        return Path(v) if isinstance(v, str) else v

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
