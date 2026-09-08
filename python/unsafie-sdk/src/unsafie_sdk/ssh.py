import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unsafie_sdk.client import client
from unsafie_sdk.errors import UnsafieError


@dataclass(frozen=True)
class Result:
    host: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def __str__(self) -> str:
        return self.output


def hosts() -> list[dict]:
    """The servers this user has added, with alias, target and pinned fingerprint."""
    return client().call("GET", "/ssh/hosts").get("hosts", [])


def run(command: str, host: str | None = None, timeout: float | None = None) -> Result:
    """Run a command on one of the user's own servers. Destructive things only when asked."""
    answer = client().call(
        "POST", "/ssh/run", {"command": command, "host": host, "timeout": timeout},
        timeout=(timeout or 120) + 60,
    )
    return Result(str(answer["host"]), int(answer["exit_code"]), str(answer.get("output") or ""))


def read(path: str, host: str | None = None) -> str:
    """Read a text file from a server."""
    answer = client().call("POST", "/ssh/read", {"command": path, "host": host})
    return str(answer["content"])


def write(path: str, content: str, host: str | None = None) -> int:
    """Write a text file to a server."""
    return int(client().call("POST", "/ssh/write", {"path": path, "content": content, "host": host})["bytes"])


def key() -> dict:
    """The account's own key pair and the known hosts entries of its servers."""
    return client().call("GET", "/ssh/key")


def install(home: str | Path | None = None) -> Path:
    """Put the account's private key on this machine so plain ssh and git over ssh work."""
    material = key()
    root = Path(home or os.environ.get("HOME") or Path.home()) / ".ssh"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(stat.S_IRWXU)
    private = root / "id_ed25519"
    private.write_text(material["private"], encoding="utf-8")
    private.chmod(0o600)
    (root / "id_ed25519.pub").write_text(material["public"] + "\n", encoding="utf-8")
    known = material.get("known_hosts") or []
    if known:
        (root / "known_hosts").write_text("\n".join(known) + "\n", encoding="utf-8")
    config = root / "config"
    if not config.is_file():
        config.write_text(
            "Host *\n"
            "    IdentityFile ~/.ssh/id_ed25519\n"
            "    StrictHostKeyChecking accept-new\n"
            "    ServerAliveInterval 15\n",
            encoding="utf-8",
        )
        config.chmod(0o600)
    return private


def agent() -> None:
    """Start an ssh-agent in this process and load the key into it."""
    done = subprocess.run(["ssh-agent", "-s"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise UnsafieError("no ssh-agent on this machine")
    for line in done.stdout.splitlines():
        if line.startswith(("SSH_AUTH_SOCK=", "SSH_AGENT_PID=")):
            name, _, rest = line.partition("=")
            os.environ[name] = rest.split(";")[0]
    subprocess.run(["ssh-add", str(Path.home() / ".ssh" / "id_ed25519")], check=False)
