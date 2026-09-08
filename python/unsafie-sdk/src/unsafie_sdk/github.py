import os
import subprocess
from pathlib import Path

from unsafie_sdk.client import client
from unsafie_sdk.errors import UnsafieError

BASE = "/github"

_current: str | None = None


def logins() -> list[str]:
    """Every GitHub account attached to this user, in the order they were attached."""
    rows = client().call("GET", f"{BASE}/accounts").get("accounts", [])
    return [row["login"] for row in rows]


def use(login: str | None) -> str | None:
    """Pick the account git and gh speak with; None goes back to the first one."""
    global _current
    if login is not None:
        known = logins()
        if login not in known:
            raise UnsafieError(f"no account '{login}'. Attached: {', '.join(known) or 'none'}")
    _current = login
    _wire()
    return _current


def token(repo: str | None = None, *, login: str | None = None) -> str:
    """A token for git, gh or curl: scoped to the repository when the App is installed there."""
    body = {"repo": repo, "login": login or _current}
    return str(client().call("POST", f"{BASE}/token", body)["token"])


def _wire() -> bool:
    try:
        secret = token()
    except UnsafieError:
        return False
    os.environ["GH_TOKEN"] = secret
    home = Path(os.environ.get("HOME") or Path.home())
    store = home / ".git-credentials"
    line = f"https://x-access-token:{secret}@github.com\n"
    body = store.read_text(encoding="utf-8") if store.is_file() else ""
    kept = [row for row in body.splitlines(keepends=True) if "@github.com" not in row]
    store.write_text("".join(kept) + line, encoding="utf-8")
    store.chmod(0o600)
    subprocess.run(
        ["git", "config", "--global", "credential.helper", "store"], check=False, capture_output=True
    )
    return True
