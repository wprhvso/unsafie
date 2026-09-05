from fastapi import APIRouter, Depends, HTTPException

from unsafie.api.dependencies.paging import paging
from unsafie.api.schemas.common import Ok, Page, PageParams
from unsafie.api.schemas.models import ScheduleRead
from unsafie.database import SessionLocal
from unsafie.database.repositories.schedule import ScheduleRepository

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("", response_model=Page[ScheduleRead])
async def list_schedule(params: PageParams = Depends(paging)):
    async with SessionLocal() as session:
        rows, total = await ScheduleRepository(session).page(params.offset, params.limit)
    return Page.of([ScheduleRead.model_validate(r) for r in rows], total, params)


@router.post("/{task_id}/pause", response_model=ScheduleRead)
async def pause(task_id: int, resume: bool = False):
    async with SessionLocal() as session:
        repo = ScheduleRepository(session)
        task = await repo.get_any(task_id)
        if task is None:
            raise HTTPException(404, "no such task")
        await repo.set_enabled(task, resume)
    return ScheduleRead.model_validate(task)


@router.delete("/{task_id}", response_model=Ok)
async def delete_task(task_id: int):
    async with SessionLocal() as session:
        repo = ScheduleRepository(session)
        task = await repo.get_any(task_id)
        if task is None:
            raise HTTPException(404, "no such task")
        await repo.remove(task.bot_id, task.chat_id, task_id)
    return Ok()
