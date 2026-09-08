import logging

from fastapi import APIRouter

from unsafie.api.routes.cli.deps import Who
from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cli"])


@router.get("/me")
async def me(who: Who) -> dict:
    async with SessionLocal() as session:
        user = await UserRepository(session).get_or_create(who.user_id)
    return {
        "user_id": who.user_id,
        "bot_id": who.bot_id,
        "chat_id": who.chat_id,
        "machine": who.machine,
        "limits": {
            "machines": user.pool_max_machines,
            "background": user.pool_max_background,
            "minutes_day": user.pool_max_minutes_day,
            "priority": user.pool_priority,
            "blocked": user.pool_blocked,
        },
        "token": {
            "name": who.token.name,
            "kind": who.token.kind,
            "scopes": sorted(who.token.scope_set),
            "created_at": who.token.created_at,
            "expires_at": who.token.expires_at,
        },
    }
