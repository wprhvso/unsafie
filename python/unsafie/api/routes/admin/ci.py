from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from unsafie.database import SessionLocal
from unsafie.database.models.ci import CiRun
from unsafie.database.repositories.ci import CiRepository

router = APIRouter(prefix="/ci", tags=["admin-ci"])

class WhitelistAddRequest(BaseModel):
    login: str

@router.get("/whitelist")
async def get_whitelist():
    async with SessionLocal() as session:
        items = await CiRepository(session).list_whitelist()
        return [{"github_login": i.github_login, "added_by": i.added_by, "created_at": i.created_at.isoformat()} for i in items]

@router.post("/whitelist")
async def add_to_whitelist(req: WhitelistAddRequest):
    login = req.login.strip().lstrip("@")
    if not login:
        raise HTTPException(400, "login required")
    async with SessionLocal() as session:
        item = await CiRepository(session).add_to_whitelist(login, added_by="admin")
        return {"ok": True, "github_login": item.github_login}

@router.delete("/whitelist/{login}")
async def delete_from_whitelist(login: str):
    async with SessionLocal() as session:
        ok = await CiRepository(session).remove_from_whitelist(login)
        return {"ok": ok}

@router.get("/overview")
async def get_overview():
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count(CiRun.id)))
        pending = await session.scalar(select(func.count(CiRun.id)).where(CiRun.status == "pending"))
        in_progress = await session.scalar(select(func.count(CiRun.id)).where(CiRun.status == "in_progress"))
        success = await session.scalar(select(func.count(CiRun.id)).where(CiRun.status == "success"))
        failure = await session.scalar(select(func.count(CiRun.id)).where(CiRun.status.in_(["failure", "crash"])))
        return {
            "total": total or 0,
            "pending": pending or 0,
            "in_progress": in_progress or 0,
            "success": success or 0,
            "failure": failure or 0,
        }
