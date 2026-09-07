from fastapi import APIRouter

from unsafie.api.routes.cli.chat import router as chat_router
from unsafie.api.routes.cli.me import router as me_router
from unsafie.api.routes.cli.pages import router as pages_router

cli_router = APIRouter(prefix="/api/v1")
cli_router.include_router(me_router)
cli_router.include_router(chat_router)
cli_router.include_router(pages_router)

__all__ = ["cli_router"]
