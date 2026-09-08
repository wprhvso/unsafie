import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie import tokens
from unsafie.fluent import t
from unsafie.settings import settings
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)

NAME_LIMIT = 64


def build_auth_router() -> Router:
    router = Router()

    @router.message(Command("auth"))
    async def auth_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        parts = (command.args or "").split()
        action = parts[0].lower() if parts else ""

        if action in ("list", "ls"):
            issued = await tokens.listing(user_id)
            if not issued:
                await answer(message, bot_id, t("auth-empty", locale))
                return
            lines = [t("auth-list", locale)]
            for token in issued:
                used = token.last_used_at.strftime("%d.%m %H:%M") if token.last_used_at else "—"
                lines.append(f"· `{token.name}` · {token.kind} · {used}")
            await answer(message, bot_id, "\n".join(lines))
            return

        if action in ("rm", "revoke", "del"):
            if len(parts) < 2:
                await answer(message, bot_id, t("auth-usage", locale))
                return
            gone = await tokens.revoke(user_id, parts[1])
            key = "auth-revoked" if gone else "auth-unknown"
            await answer(message, bot_id, t(key, locale, name=parts[1]))
            return

        if action and action not in ("new", "token"):
            await answer(message, bot_id, t("auth-usage", locale))
            return

        name = parts[1][:NAME_LIMIT] if len(parts) > 1 else "telegram"
        await tokens.revoke(user_id, name)
        _, raw = await tokens.issue(
            user_id=user_id,
            bot_id=bot_id,
            chat_id=message.chat.id,
            name=name,
        )
        logger.info("user=%s issued cli token '%s'", user_id, name)
        await answer(
            message,
            bot_id,
            t("auth-issued", locale, name=name, api=settings.public_origin) + f"\n\n`{raw}`",
        )

    return router
