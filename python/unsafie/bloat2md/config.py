import functools

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BLOAT2MD_",
        extra="ignore",
        frozen=True,
    )

    host: str = "127.0.0.1"
    port: int = 8084
    env: str = "prod"
    otel_exporter_otlp_endpoint: str = "http://alloy:4317"

    timeout: float = Field(default=30.0, gt=0)
    memory_limit_mb: int = Field(default=512, gt=0)
    cpu_seconds: int = Field(default=20, gt=0)
    output_limit_mb: int = Field(default=64, gt=0)

    input_limit_mb: float = Field(default=20.0, gt=0)
    max_pages: int = Field(default=50, gt=0)
    max_render_pages: int = Field(default=10, ge=0)
    render_edge: int = Field(default=1536, gt=0)
    render_quality: int = Field(default=80, gt=0, le=100)
    max_markdown_chars: int = Field(default=200_000, gt=0)
    max_image_pixels: int = Field(default=50_000_000, gt=0)
    max_archive_members: int = Field(default=2000, gt=0)
    max_archive_ratio: int = Field(default=100, gt=0)
    max_archive_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    libreoffice: bool = True


@functools.lru_cache(maxsize=1)
def settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigError(str(error)) from error


def reset() -> None:
    settings.cache_clear()
