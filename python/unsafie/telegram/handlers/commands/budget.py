import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.agent.billing import parse_usd, units_to_usd
from unsafie.database import SessionLocal
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def _amount(locale: str, units: int) -> str:
    return t("commands-budget-amount", locale, amount=units_to_usd(units))


def _status(locale: str, balance: int, locked: int, budget: int) -> str:
    lines = [t("commands-budget-balance", locale, amount=_amount(locale, balance))]
    if locked > 0:
        lines.append(t("commands-budget-locked", locale, amount=_amount(locale, locked)))
        free = max(balance - locked, 0)
        lines.append(t("commands-budget-available", locale, amount=_amount(locale, free)))
    limit = t("commands-budget-unlimited", locale) if budget < 0 else _amount(locale, budget)
    lines.append(t("commands-budget-limit", locale, limit=limit))
    return "\n".join(lines)


def build_budget_router() -> Router:
    router = Router()

    @router.message(Command("budget"))
    async def budget_handler(message: Message, command: CommandObject, bot_id: int) -> None:
        if message.from_user is None:
            return
        user_id = message.from_user.id
        locale = await locale_for(user_id, message.from_user)
        raw = (command.args or "").strip()
        async with SessionLocal() as session:
            users = UserRepository(session)
            user = await users.get_or_create(user_id)
            locked = await TurnRepository(session).locked_for(user_id)
            if not raw:
                await answer(message, bot_id, _status(locale, user.balance, locked, user.budget))
                return
            value = parse_usd(raw)
            if value is None:
                await answer(message, bot_id, t("commands-budget-usage", locale))
                return
            await users.set_budget(user_id, value)
        logger.info("bot=%s user=%s budget -> %s", bot_id, user_id, value)
        if value == 0:
            await answer(message, bot_id, t("commands-budget-zero", locale))
            return
        await answer(message, bot_id, _status(locale, user.balance, locked, value))

    return router
