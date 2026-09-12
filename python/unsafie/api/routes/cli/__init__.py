from fastapi import APIRouter

from unsafie.api.routes.cli.automation import router as automation_router
from unsafie.api.routes.cli.chat import router as chat_router
from unsafie.api.routes.cli.ci import router as ci_router
from unsafie.api.routes.cli.email import router as email_router
from unsafie.api.routes.cli.github import router as github_router
from unsafie.api.routes.cli.inline import router as inline_router
from unsafie.api.routes.cli.pages import router as pages_router
from unsafie.api.routes.cli.pool import router as pool_router
from unsafie.api.routes.cli.ssh import router as ssh_router
from unsafie.api.routes.cli.store import router as store_router

cli_router = APIRouter(prefix="/api/v1")
cli_router.include_router(chat_router)
cli_router.include_router(inline_router)
cli_router.include_router(pages_router)
cli_router.include_router(pool_router)
cli_router.include_router(store_router)
cli_router.include_router(github_router)
cli_router.include_router(ci_router)
cli_router.include_router(automation_router)
cli_router.include_router(ssh_router)
cli_router.include_router(email_router)

__all__ = ["cli_router"]
