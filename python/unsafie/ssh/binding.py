import logging
import re

from unsafie.database import SessionLocal
from unsafie.database.models.ssh_host import SshHost
from unsafie.database.repositories.ssh import SshRepository
from unsafie.ssh.errors import SshError

logger = logging.getLogger(__name__)

TARGET_RE = re.compile(r"^(?:(?P<user>[^@\s]+)@)?(?P<host>[^:\s]+)(?::(?P<port>\d+))?$")
ALIAS_RE = re.compile(r"^[a-zA-Z0-9][\w.-]{0,31}$")


def parse_target(raw: str) -> tuple[str, int, str | None]:
    m = TARGET_RE.match((raw or "").strip())
    if not m:
        raise SshError(f"cannot parse '{raw}'; expected [user@]host[:port]")
    port = int(m.group("port") or 22)
    if not 1 <= port <= 65535:
        raise SshError(f"port {port} is out of range")
    return m.group("host"), port, m.group("user")


def check_alias(alias: str) -> str:
    alias = (alias or "").strip()
    if not ALIAS_RE.match(alias):
        raise SshError("alias must be 1–32 chars: letters, digits, dot, dash, underscore")
    return alias


async def add(user_id: int, alias: str, target: str, username: str | None) -> SshHost:
    alias = check_alias(alias)
    host, port, parsed_user = parse_target(target)
    login = username or parsed_user
    if not login:
        raise SshError("a username is required: user@host or a separate argument")
    async with SessionLocal() as session:
        repo = SshRepository(session)
        for existing in await repo.hosts(user_id):
            if existing.alias == alias:
                raise SshError(f"alias '{alias}' is already taken by {existing.label}")
            if (existing.host, existing.port, existing.username) == (host, port, login):
                raise SshError(f"this host is already added as '{existing.alias}'")
        return await repo.add(user_id, alias, host, port, login, None, None)


async def remove(user_id: int, ref: str) -> SshHost:
    async with SessionLocal() as session:
        removed = await SshRepository(session).remove(user_id, ref)
    if removed is None:
        raise SshError(f"no host '{ref}'")
    return removed


async def resolve(user_id: int, ref: str | None) -> SshHost:
    async with SessionLocal() as session:
        repo = SshRepository(session)
        hosts = await repo.hosts(user_id)
        if not hosts:
            raise SshError("no servers added. Ask the user to add one: /ssh add alias user@host")
        if ref:
            found = await repo.host(user_id, ref)
            if found is None:
                known = ", ".join(h.alias for h in hosts)
                raise SshError(f"no host '{ref}'. Available: {known}")
            return found
        if len(hosts) > 1:
            known = ", ".join(h.alias for h in hosts)
            raise SshError(f"specify the host: {known}")
        return hosts[0]


async def hosts(user_id: int) -> list[SshHost]:
    async with SessionLocal() as session:
        return await SshRepository(session).hosts(user_id)


def describe(host: SshHost) -> str:
    fingerprint = f" · {host.fingerprint}" if host.fingerprint else " · not connected yet"
    return f"{host.alias} → {host.label}{fingerprint}"
