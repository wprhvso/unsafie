from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Ok, Page, PageParams
from unsafie.api.schemas.models import SshHostRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.ssh import SshRepository
from unsafie.ssh.pool import pool

router = APIRouter(prefix="/ssh", tags=["ssh"])


@router.get("/hosts", response_model=Page[SshHostRead])
async def list_hosts(params: PageParams = Depends(paging)):
    live = {(s["user_id"], s["host_id"]) for s in pool.stats() if s["alive"]}
    async with SessionLocal() as session:
        rows, total = await SshRepository(session).page(params.offset, params.limit)
    items = [SshHostRead(**{**r.__dict__, "connected": (r.user_id, r.id) in live}) for r in rows]
    return Page.of(items, total, params)


@router.get("/connections")
async def list_connections():
    return pool.stats()


@router.post("/hosts/{host_id}/disconnect", response_model=Ok)
async def disconnect(host_id: int):
    async with SessionLocal() as session:
        host = await SshRepository(session).get(host_id)
    if host is None:
        raise HTTPException(404, "no such host")
    closed = await pool.disconnect(host.user_id, host_id)
    return Ok(detail="disconnected" if closed else "was not connected")
