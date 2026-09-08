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


def identity(*, login: str | None = None) -> dict[str, str] | None:
    """The name and email git commits are signed with: the owner of the token, not unsafie."""
    body = {"repo": None, "login": login or _current}
    answer = client().call("POST", f"{BASE}/token", body)
    name, email = str(answer.get("name") or ""), str(answer.get("email") or "")
    return {"name": name, "email": email} if name and email else None


def _wire() -> bool:
    try:
        answer = client().call("POST", f"{BASE}/token", {"repo": None, "login": _current})
    except UnsafieError:
        return False
    secret = str(answer["token"])
    os.environ["GH_TOKEN"] = secret
    _sign(str(answer.get("name") or ""), str(answer.get("email") or ""))
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


def _sign(name: str, email: str) -> None:
    """Commits belong to the owner of the token, so git is told who that is."""
    if not name or not email:
        return
    for line in (
        ["git", "config", "--global", "user.name", name],
        ["git", "config", "--global", "user.email", email],
    ):
        subprocess.run(line, check=False, capture_output=True)
    os.environ["GIT_AUTHOR_NAME"] = os.environ["GIT_COMMITTER_NAME"] = name
    os.environ["GIT_AUTHOR_EMAIL"] = os.environ["GIT_COMMITTER_EMAIL"] = email
