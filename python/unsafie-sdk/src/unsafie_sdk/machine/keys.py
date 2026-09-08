"""The owner's ssh key and host aliases, put on the machine when the lease starts."""

import os
import stat
from pathlib import Path

from unsafie_sdk.client import client

WILDCARD = (
    "Host *\n"
    "    IdentityFile ~/.ssh/id_ed25519\n"
    "    StrictHostKeyChecking accept-new\n"
    "    ServerAliveInterval 15\n"
)


def install(home: str | Path | None = None) -> list[str]:
    """Write the key, the known hosts and a Host block per server, so `ssh prod` just works."""
    material = client().call("GET", "/ssh/key")
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
    hosts = client().call("GET", "/ssh/hosts").get("hosts", [])
    config = root / "config"
    config.write_text(_config(hosts), encoding="utf-8")
    config.chmod(0o600)
    return [str(row["alias"]) for row in hosts if row.get("alias")]


def _config(hosts: list[dict]) -> str:
    blocks = []
    for row in hosts:
        alias = str(row.get("alias") or "").strip()
        target = str(row.get("host") or "").strip()
        if not alias or not target:
            continue
        block = [f"Host {alias}", f"    HostName {target}"]
        if row.get("user"):
            block.append(f"    User {row['user']}")
        if row.get("port") and int(row["port"]) != 22:
            block.append(f"    Port {int(row['port'])}")
        blocks.append("\n".join(block) + "\n")
    blocks.append(WILDCARD)
    return "\n".join(blocks)
