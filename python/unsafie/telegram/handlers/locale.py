from aiogram.types import User as TgUser

from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository
from unsafie.settings import settings

KNOWN = {"en", "ru"}


def guess(tg_user: TgUser | None) -> str:
    code = (tg_user.language_code or "").lower()[:2] if tg_user else ""
    return code if code in KNOWN else settings.default_locale


async def locale_for(user_id: int, tg_user: TgUser | None = None) -> str:
    async with SessionLocal() as session:
        user = await UserRepository(session).get(user_id)
    if user is not None and user.locale:
        return user.locale
    return guess(tg_user)
