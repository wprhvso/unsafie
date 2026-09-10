from fastapi import APIRouter

from unsafie.api.routes.public.artifacts import router as artifact_router
from unsafie.api.routes.public.auth import router as auth_router
from unsafie.api.routes.public.github import router as github_router
from unsafie.api.routes.public.live import router as live_router
from unsafie.api.routes.public.machine import router as machine_router
from unsafie.api.routes.public.telegram import router as telegram_router

public_router = APIRouter()
public_router.include_router(auth_router)
public_router.include_router(github_router)
public_router.include_router(live_router)
public_router.include_router(machine_router)
public_router.include_router(telegram_router)

__all__ = ["artifact_router", "public_router"]
