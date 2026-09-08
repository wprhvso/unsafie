import os
import subprocess
from pathlib import Path

from unsafie.cli.client import client

BASE = "/github"


def logins() -> list[str]:
    rows = client().call("GET", f"{BASE}/accounts").get("accounts", [])
    return [row["login"] for row in rows]


def use(login: str | None) -> dict:
    answer = client().call("POST", f"{BASE}/token", {"repo": None, "login": login})
    secret = str(answer["token"])
    name, email = str(answer.get("name") or ""), str(answer.get("email") or "")
    os.environ["GH_TOKEN"] = secret
    if name and email:
        for line in (
            ["git", "config", "--global", "user.name", name],
            ["git", "config", "--global", "user.email", email],
        ):
            subprocess.run(line, check=False, capture_output=True)
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
    return {"login": login, "name": name, "email": email}


def token(repo: str | None = None, *, login: str | None = None) -> dict:
    body = {"repo": repo, "login": login}
    return client().call("POST", f"{BASE}/token", body)


def identity(*, login: str | None = None) -> dict:
    body = {"repo": None, "login": login}
    answer = client().call("POST", f"{BASE}/token", body)
    return {"name": str(answer.get("name") or ""), "email": str(answer.get("email") or "")}
