from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Ok, Page, PageParams
from unsafie.api.schemas.models import WatchRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.watch import WatchRepository

router = APIRouter(prefix="/watches", tags=["watches"])


def read(watch, host) -> WatchRead:
    return WatchRead(**{**watch.__dict__, "host": host.alias})


@router.get("", response_model=Page[WatchRead])
async def list_watches(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await WatchRepository(session).page(params.offset, params.limit)
    return Page.of([read(w, h) for w, h in rows], total, params)


@router.post("/{watch_id}/pause", response_model=Ok)
async def pause(watch_id: int, resume: bool = False):
    async with SessionLocal() as session:
        repo = WatchRepository(session)
        row = await repo.get_any(watch_id)
        if row is None:
            raise HTTPException(404, "no such check")
        row.enabled = resume
        if resume:
            row.fails = 0
        await repo.save()
    return Ok(detail="resumed" if resume else "paused")


@router.post("/{watch_id}/run", response_model=Ok)
async def run_now(watch_id: int):
    from unsafie.database.repositories.ssh import SshRepository
    from unsafie.ssh.errors import SshError
    from unsafie.ssh.watchdog import run_once

    async with SessionLocal() as session:
        repo = WatchRepository(session)
        row = await repo.get_any(watch_id)
        if row is None:
            raise HTTPException(404, "no such check")
        host = await SshRepository(session).get(row.host_id)
    try:
        fires, reason, result = await run_once(row, host)
    except SshError as e:
        raise HTTPException(502, str(e)) from None
    return Ok(detail=f"{'fires' if fires else 'quiet'}: {reason}; exit={result.exit_code}")


@router.delete("/{watch_id}", response_model=Ok)
async def delete_watch(watch_id: int):
    async with SessionLocal() as session:
        repo = WatchRepository(session)
        row = await repo.get_any(watch_id)
        if row is None:
            raise HTTPException(404, "no such check")
        await repo.remove(row.bot_id, row.chat_id, watch_id)
    return Ok()
