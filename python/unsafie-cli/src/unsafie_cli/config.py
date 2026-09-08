import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from unsafie_cli.errors import Usage

DEFAULT_API = "https://unsafie.com"

KEYS = ("token", "api", "chat", "machine", "format", "admin")
ENV = {
    "token": "UNSAFIE_TOKEN",
    "api": "UNSAFIE_API",
    "chat": "UNSAFIE_CHAT",
    "machine": "UNSAFIE_MACHINE",
    "format": "UNSAFIE_FORMAT",
    "admin": "UNSAFIE_ADMIN_TOKEN",
}
DEFAULTS = {"api": DEFAULT_API, "format": "text"}


@dataclass(frozen=True, slots=True)
class Value:
    value: str
    source: str


def home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "unsafie"


def path() -> Path:
    return home() / "config.toml"


def load() -> dict[str, str]:
    target = path()
    if not target.is_file():
        return {}
    try:
        raw = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as broken:
        raise Usage(f"cannot read {target}: {broken}", "fix it by hand or delete the file") from None
    return {k: str(v) for k, v in raw.items() if k in KEYS}


def save(values: dict[str, str]) -> Path:
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f'{key} = "{values[key]}"\n' for key in KEYS if values.get(key))
    target.write_text(body, encoding="utf-8")
    target.chmod(0o600)
    return target


def check(key: str) -> str:
    if key not in KEYS:
        raise Usage(f"unknown setting '{key}'", f"known settings: {', '.join(KEYS)}")
    return key


def resolve(key: str, override: str | None = None) -> Value | None:
    check(key)
    if override:
        return Value(override, "flag")
    from_env = os.environ.get(ENV[key])
    if from_env:
        return Value(from_env, ENV[key])
    from_file = load().get(key)
    if from_file:
        return Value(from_file, str(path()))
    fallback = DEFAULTS.get(key)
    if fallback:
        return Value(fallback, "default")
    return None


def mask(token: str) -> str:
    if len(token) <= 8:
        return "…"
    return f"{token[:4]}…{token[-4:]}"
