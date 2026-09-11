import os
import stat
from pathlib import Path

from unsafie.cli.client import Client, client

WILDCARD = (
    "Host *\n"
    "    IdentityFile ~/.ssh/id_ed25519\n"
    "    StrictHostKeyChecking accept-new\n"
    "    ServerAliveInterval 15\n"
)


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


def write_keys(
    material: dict,
    hosts: list[dict],
    home: str | Path | None = None,
) -> list[str]:
    root = Path(home or os.environ.get("HOME") or Path.home()) / ".ssh"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(stat.S_IRWXU)
    private = root / "id_ed25519"
    private.write_text(material["private"], encoding="utf-8")
    private.chmod(0o600)
    (root / "id_ed25519.pub").write_text(material["public"] + "\n", encoding="utf-8")
    known = material.get("known_hosts") or []
    if known:
        kh_file = root / "known_hosts"
        existing_kh = kh_file.read_text(encoding="utf-8").splitlines() if kh_file.exists() else []
        merged_kh = list(dict.fromkeys(existing_kh + known))
        kh_file.write_text("\n".join(merged_kh) + "\n", encoding="utf-8")
        kh_file.chmod(0o644)
    config = root / "config"
    unsafie_conf = _config(hosts)
    existing_conf = config.read_text(encoding="utf-8") if config.exists() else ""
    marker_start = "# BEGIN UNSAFIE HOSTS"
    marker_end = "# END UNSAFIE HOSTS"
    if marker_start in existing_conf and marker_end in existing_conf:
        before = existing_conf.split(marker_start)[0]
        after = existing_conf.split(marker_end)[1]
        new_conf = f"{before}{marker_start}\n{unsafie_conf}\n{marker_end}{after}"
    elif existing_conf.strip():
        new_conf = f"{existing_conf.rstrip()}\n\n{marker_start}\n{unsafie_conf}\n{marker_end}\n"
    else:
        new_conf = f"{marker_start}\n{unsafie_conf}\n{marker_end}\n"
    config.write_text(new_conf, encoding="utf-8")
    config.chmod(0o600)
    return [str(row["alias"]) for row in hosts if row.get("alias")]


def install(home: str | Path | None = None, cli: Client | None = None) -> list[str]:
    cli = cli or client()
    material = cli.call("GET", "/ssh/key")
    hosts = cli.call("GET", "/ssh/hosts").get("hosts", [])
    return write_keys(material, hosts, home=home)
