from unsafie.log import get_logger

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from unsafie.api.routes.cli.deps import Pool
from unsafie.errors import OpsError
from unsafie.settings import settings
from unsafie.ssh import binding, keys
from unsafie.ssh import pool as ssh_pool

logger = get_logger(__name__)

router = APIRouter(prefix="/ssh", tags=["cli"])


class Command(BaseModel):
    command: str
    host: str | None = None
    timeout: float | None = None


class Write(BaseModel):
    path: str
    content: str
    host: str | None = None


def _host_view(host) -> dict:
    return {
        "alias": host.alias,
        "target": host.label,
        "host": host.host,
        "port": host.port,
        "user": host.username,
        "fingerprint": host.fingerprint,
    }


@router.get("/hosts")
async def hosts(who: Pool) -> dict:
    rows = await binding.hosts(who.user_id)
    return {"hosts": [_host_view(row) for row in rows]}


@router.get("/key")
async def key(who: Pool) -> dict:
    """The account's own ssh key, so a machine can reach the servers of its owner."""
    private, public = await keys.ensure(who.user_id)
    known = []
    for host in await binding.hosts(who.user_id):
        if host.host_key:
            entry = host.host_key.strip()
            known.append(entry if host.port == 22 else f"[{host.host}]:{host.port} {entry}")
    return {"private": private, "public": public, "known_hosts": known}


@router.post("/run")
async def run(body: Command, who: Pool) -> dict:
    try:
        host = await binding.resolve(who.user_id, body.host)
        result = await ssh_pool.run(who.user_id, host, body.command, body.timeout)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {
        "host": host.alias,
        "exit_code": result.exit_code,
        "output": result.output[: settings.ssh_max_output],
    }


@router.post("/read")
async def read(body: Command, who: Pool) -> dict:
    try:
        host = await binding.resolve(who.user_id, body.host)
        data = await ssh_pool.read_file(who.user_id, host, body.command)
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    from unsafie.mime import decode_text

    decoded = decode_text(data)
    if decoded is None:
        raise HTTPException(400, f"{body.command} is binary; read it on the machine instead")
    return {"host": host.alias, "path": body.command, "content": decoded[0]}


@router.post("/write")
async def write(body: Write, who: Pool) -> dict:
    try:
        host = await binding.resolve(who.user_id, body.host)
        size = await ssh_pool.write_file(who.user_id, host, body.path, body.content.encode())
    except OpsError as refused:
        raise HTTPException(400, str(refused)) from None
    return {"host": host.alias, "path": body.path, "bytes": size}
