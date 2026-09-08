import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from unsafie_sdk.client import client
from unsafie_sdk.errors import UnsafieError

_current: str | None = None


def accounts() -> list[dict]:
    """Every GitHub account attached to this user: login, scopes, whether a token is stored."""
    return client().call("GET", "/accounts").get("accounts", [])


def logins() -> list[str]:
    """Just the usernames, in the order they were attached."""
    return [row["login"] for row in accounts()]


def use(login: str | None) -> str | None:
    """Pick which account the next calls speak with; None goes back to the first one."""
    global _current
    if login is not None:
        known = logins()
        if login not in known:
            raise UnsafieError(f"no account '{login}'. Attached: {', '.join(known) or 'none'}")
    _current = login
    return _current


def current() -> str | None:
    """The account chosen with use(), or None while the default one is in play."""
    return _current


def add(token: str) -> dict:
    """Attach a personal access token. Same login replaces its token, a new login sits beside it."""
    return client().call("POST", "/accounts", {"token": token})


def forget(login: str) -> dict:
    """Detach an account by login."""
    if _current == login:
        use(None)
    return client().call("DELETE", f"/accounts/{login}")


def token(repo: str | None = None, *, login: str | None = None) -> str:
    """A token for git, gh or curl: scoped to the repository when the App is installed there."""
    body = {"repo": repo, "login": login or _current}
    return str(client().call("POST", "/token", body)["token"])


def api(path: str, method: str = "GET", body: dict | None = None, **params) -> Any:
    """Call the GitHub API as the chosen account: api('/user'), api('/repos/o/n/issues')."""
    payload = {
        "path": path,
        "method": method,
        "body": body,
        "params": params or None,
        "login": _current,
    }
    return client().call("POST", "/api", payload).get("result")


def repos(limit: int = 100) -> list[dict]:
    """Repositories this user has bound to the bot."""
    return client().call("GET", "/repos", params={"limit": limit}).get("repos", [])


def bind(ref: str, alias: str | None = None) -> dict:
    """Bind a repository so webhooks and CI can reach it."""
    return client().call("POST", "/repos", {"ref": ref, "alias": alias})


def unbind(ref: str) -> dict:
    """Unbind a repository."""
    return client().call("DELETE", f"/repos/{ref}")


def sync() -> list[dict]:
    """Refresh the list of repositories from GitHub."""
    return client().call("POST", "/repos/sync").get("repos", [])


def clone(repo: str, directory: str | Path | None = None, *, branch: str | None = None, depth=None):
    """Clone a repository into the working directory with credentials already wired in."""
    where = Path(directory) if directory else Path.cwd() / repo.split("/")[-1]
    secret = token(repo)
    url = f"https://x-access-token:{secret}@github.com/{repo}.git"
    line = ["git", "clone"]
    if branch:
        line += ["--branch", branch]
    if depth:
        line += ["--depth", str(int(depth))]
    line += [url, str(where)]
    done = subprocess.run(line, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise UnsafieError(f"clone failed: {done.stderr.strip()[-400:]}")
    subprocess.run(
        ["git", "-C", str(where), "remote", "set-url", "origin", f"https://github.com/{repo}.git"],
        check=False,
        capture_output=True,
    )
    _credentials(secret)
    return where


def _credentials(secret: str) -> None:
    home = Path(os.environ.get("HOME") or Path.home())
    store = home / ".git-credentials"
    line = f"https://x-access-token:{secret}@github.com\n"
    body = store.read_text(encoding="utf-8") if store.is_file() else ""
    if line not in body:
        store.write_text(body + line, encoding="utf-8")
        store.chmod(0o600)
    subprocess.run(
        ["git", "config", "--global", "credential.helper", "store"], check=False, capture_output=True
    )


def gh(*args: str, check: bool = True) -> str:
    """Run the gh CLI with the chosen account's token: gh('pr', 'create', '--fill')."""
    environment = dict(os.environ, GH_TOKEN=token(), GH_PROMPT_DISABLED="1")
    done = subprocess.run(["gh", *args], capture_output=True, text=True, env=environment, check=False)
    if check and done.returncode != 0:
        raise UnsafieError(f"gh {shlex.join(args)} failed: {done.stderr.strip()[-400:]}")
    return done.stdout
