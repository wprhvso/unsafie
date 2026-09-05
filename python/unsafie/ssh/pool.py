import asyncio
import base64
import hashlib
import logging
import time
from dataclasses import dataclass, field

import asyncssh

from unsafie import telemetry
from unsafie.database import SessionLocal
from unsafie.database.models.ssh_host import SshHost
from unsafie.database.repositories.ssh import SshRepository
from unsafie.settings import settings
from unsafie.ssh import keys
from unsafie.ssh.errors import HostKeyChanged, NoKey, SshError
from unsafie.telemetry import attrs

logger = logging.getLogger(__name__)


def fingerprint(key: asyncssh.SSHKey) -> str:
    digest = hashlib.sha256(key.public_data).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


@dataclass
class Held:
    connection: asyncssh.SSHClientConnection
    last_used: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_used = time.monotonic()

    @property
    def idle(self) -> float:
        return time.monotonic() - self.last_used

    @property
    def alive(self) -> bool:
        return not self.connection.is_closed()


class Pool:
    def __init__(self) -> None:
        self._held: dict[tuple[int, int], Held] = {}
        self._locks: dict[tuple[int, int], asyncio.Lock] = {}

    def _lock(self, key: tuple[int, int]) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def stats(self) -> list[dict]:
        return [
            {"user_id": u, "host_id": h, "idle_sec": round(held.idle), "alive": held.alive}
            for (u, h), held in self._held.items()
        ]

    @telemetry.traced("ssh.connect", kind=telemetry.CLIENT)
    async def connect(self, user_id: int, host: SshHost) -> asyncssh.SSHClientConnection:
        telemetry.annotate(
            **{
                attrs.SSH_ALIAS: host.alias,
                attrs.SERVER_ADDRESS: host.host,
                attrs.SERVER_PORT: host.port,
                attrs.USER_ID: user_id,
            }
        )
        key = (user_id, host.id)
        async with self._lock(key):
            held = self._held.get(key)
            if held is not None:
                if held.alive and held.idle < settings.ssh_idle_timeout:
                    held.touch()
                    telemetry.annotate(**{attrs.SSH_REUSED: True})
                    return held.connection
                await self._drop(key)
            pair = await keys.get(user_id)
            if pair is None:
                raise NoKey
            private = keys.load(pair[0])
            logger.info("user=%s ssh connect %s (%s)", user_id, host.alias, host.label)
            try:
                connection = await asyncio.wait_for(
                    asyncssh.connect(
                        host.host,
                        port=host.port,
                        username=host.username,
                        client_keys=[private],
                        known_hosts=None,
                        keepalive_interval=settings.ssh_keepalive,
                        connect_timeout=settings.ssh_connect_timeout,
                    ),
                    timeout=settings.ssh_connect_timeout + 5,
                )
            except asyncssh.PermissionDenied as e:
                raise SshError(
                    f"{host.alias}: the server refused the key ({e}). The user must add the public "
                    "key from /ssh key to ~/.ssh/authorized_keys of "
                    f"{host.username}@{host.host}."
                ) from None
            except (TimeoutError, asyncssh.Error, OSError) as e:
                raise SshError(f"{host.alias}: cannot connect ({type(e).__name__}: {e})") from None
            server_key = connection.get_server_host_key()
            got = fingerprint(server_key)
            if host.fingerprint and host.fingerprint != got:
                connection.abort()
                raise HostKeyChanged(host.alias, host.fingerprint, got)
            if not host.fingerprint:
                async with SessionLocal() as session:
                    await SshRepository(session).set_host_key(
                        host.id, server_key.export_public_key().decode().strip(), got
                    )
                host.fingerprint = got
                logger.info("user=%s ssh %s host key pinned %s", user_id, host.alias, got)
            async with SessionLocal() as session:
                await SshRepository(session).touch(host.id)
            self._held[key] = Held(connection)
            return connection

    async def _drop(self, key: tuple[int, int]) -> None:
        held = self._held.pop(key, None)
        if held is not None:
            held.connection.close()
            try:
                await held.connection.wait_closed()
            except Exception:
                pass

    async def disconnect(self, user_id: int, host_id: int) -> bool:
        key = (user_id, host_id)
        if key not in self._held:
            return False
        await self._drop(key)
        logger.info("user=%s host=%s disconnected", user_id, host_id)
        return True

    async def close_all(self) -> None:
        for key in list(self._held):
            await self._drop(key)

    async def sweep(self) -> int:
        stale = [
            k for k, h in self._held.items() if not h.alive or h.idle > settings.ssh_idle_timeout
        ]
        for key in stale:
            await self._drop(key)
        return len(stale)


pool = Pool()


@dataclass(frozen=True)
class Result:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False

    @property
    def output(self) -> str:
        parts = [self.stdout.rstrip()]
        if self.stderr.strip():
            parts.append("--- stderr ---\n" + self.stderr.rstrip())
        return "\n".join(p for p in parts if p)


def _clip(value: str) -> tuple[str, bool]:
    limit = settings.ssh_max_output
    if len(value) <= limit:
        return value, False
    return value[:limit] + f"\n…(truncated, {len(value)} chars total)", True


async def run(user_id: int, host: SshHost, command: str, timeout: float | None = None) -> Result:
    with telemetry.span(
        "ssh.exec",
        kind=telemetry.CLIENT,
        attributes={
            attrs.SSH_ALIAS: host.alias,
            attrs.SERVER_ADDRESS: host.host,
            attrs.USER_ID: user_id,
            # The same 200 characters the log line carries: enough to recognise the command.
            attrs.SSH_COMMAND: telemetry.clip(command, 200),
        },
    ) as span:
        connection = await pool.connect(user_id, host)
        limit = min(
            float(timeout or settings.ssh_command_timeout), settings.ssh_max_command_timeout
        )
        started = time.perf_counter()
        try:
            completed = await asyncio.wait_for(connection.run(command, check=False), timeout=limit)
        except TimeoutError:
            raise SshError(
                f"{host.alias}: command timed out after {limit:.0f}s: {command[:200]}"
            ) from None
        except asyncssh.Error as e:
            await pool.disconnect(user_id, host.id)
            raise SshError(f"{host.alias}: {e}") from None
        stdout, cut1 = _clip(str(completed.stdout or ""))
        stderr, cut2 = _clip(str(completed.stderr or ""))
        telemetry.set_attrs(
            span,
            {
                attrs.SSH_EXIT: int(completed.exit_status or 0),
                attrs.SSH_TRUNCATED: cut1 or cut2,
                attrs.SSH_BYTES: len(stdout) + len(stderr),
            },
        )
        logger.info(
            "user=%s ssh %s exit=%s in %.0fms: %s",
            user_id,
            host.alias,
            completed.exit_status,
            (time.perf_counter() - started) * 1000,
            command[:200],
        )
        return Result(int(completed.exit_status or 0), stdout, stderr, cut1 or cut2)


@telemetry.traced("ssh.read", kind=telemetry.CLIENT)
async def read_file(user_id: int, host: SshHost, path: str) -> bytes:
    telemetry.annotate(**{attrs.SSH_ALIAS: host.alias, attrs.SSH_PATH: path})
    connection = await pool.connect(user_id, host)
    try:
        async with connection.start_sftp_client() as sftp:
            info = await sftp.stat(path)
            if info.size and info.size > settings.ssh_max_file_bytes:
                raise SshError(
                    f"{path} is {info.size} bytes, limit is {settings.ssh_max_file_bytes}"
                )
            async with sftp.open(path, "rb") as f:
                return await f.read()
    except asyncssh.SFTPNoSuchFile:
        raise SshError(f"{host.alias}: {path} does not exist") from None
    except asyncssh.SFTPPermissionDenied:
        raise SshError(f"{host.alias}: no permission to read {path}") from None
    except asyncssh.Error as e:
        raise SshError(f"{host.alias}: sftp error: {e}") from None


@telemetry.traced("ssh.write", kind=telemetry.CLIENT)
async def write_file(user_id: int, host: SshHost, path: str, data: bytes) -> int:
    telemetry.annotate(
        **{attrs.SSH_ALIAS: host.alias, attrs.SSH_PATH: path, attrs.SSH_BYTES: len(data)}
    )
    if len(data) > settings.ssh_max_file_bytes:
        raise SshError(f"file is {len(data)} bytes, limit is {settings.ssh_max_file_bytes}")
    connection = await pool.connect(user_id, host)
    try:
        async with connection.start_sftp_client() as sftp:
            async with sftp.open(path, "wb") as f:
                await f.write(data)
    except asyncssh.SFTPPermissionDenied:
        raise SshError(f"{host.alias}: no permission to write {path}") from None
    except asyncssh.SFTPNoSuchFile:
        raise SshError(f"{host.alias}: the directory for {path} does not exist") from None
    except asyncssh.Error as e:
        raise SshError(f"{host.alias}: sftp error: {e}") from None
    return len(data)


@telemetry.traced("ssh.list", kind=telemetry.CLIENT)
async def list_dir(user_id: int, host: SshHost, path: str) -> list[str]:
    telemetry.annotate(**{attrs.SSH_ALIAS: host.alias, attrs.SSH_PATH: path})
    connection = await pool.connect(user_id, host)
    try:
        async with connection.start_sftp_client() as sftp:
            names = await sftp.readdir(path)
    except asyncssh.SFTPNoSuchFile:
        raise SshError(f"{host.alias}: {path} does not exist") from None
    except asyncssh.Error as e:
        raise SshError(f"{host.alias}: sftp error: {e}") from None
    out = []
    for entry in names:
        name = entry.filename
        if name in (".", ".."):
            continue
        suffix = "/" if entry.attrs.permissions and (entry.attrs.permissions & 0o40000) else ""
        out.append(f"{name}{suffix}")
    return sorted(out)
