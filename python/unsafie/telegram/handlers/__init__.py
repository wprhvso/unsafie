from aiogram import Router

from unsafie.telegram.handlers.callbacks import build_callbacks_router
from unsafie.telegram.handlers.commands import build_commands_router
from unsafie.telegram.handlers.messages import build_messages_router
from unsafie.telegram.handlers.reactions import build_reactions_router


def build_router() -> Router:
    router = Router()
    router.include_router(build_commands_router())
    router.include_router(build_reactions_router())
    router.include_router(build_callbacks_router())
    router.include_router(build_messages_router())
    return router
