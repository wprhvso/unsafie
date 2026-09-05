from fastapi import APIRouter

from unsafie.api.routes.public.auth import router as auth_router
from unsafie.api.routes.public.github import router as github_router
from unsafie.api.routes.public.share import router as share_router

public_router = APIRouter()
public_router.include_router(auth_router)
public_router.include_router(github_router)

__all__ = ["public_router", "share_router"]
