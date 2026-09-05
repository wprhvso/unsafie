from aiogram import Router

from unsafie.telegram.handlers.commands.budget import build_budget_router
from unsafie.telegram.handlers.commands.gh import build_gh_router
from unsafie.telegram.handlers.commands.ssh import build_ssh_router
from unsafie.telegram.handlers.commands.start import build_start_router
from unsafie.telegram.handlers.commands.tasks import build_tasks_router
from unsafie.telegram.handlers.commands.tz import build_tz_router


def build_commands_router() -> Router:
    router = Router()
    for build in (
        build_start_router,
        build_budget_router,
        build_gh_router,
        build_ssh_router,
        build_tasks_router,
        build_tz_router,
    ):
        router.include_router(build())
    return router
