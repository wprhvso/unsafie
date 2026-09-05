import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from unsafie.agent.billing import UNITS_PER_USD, units_to_usd
from unsafie.database import SessionLocal
from unsafie.database.repositories.user import UserRepository
from unsafie.fluent import t
from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.sender import answer

logger = logging.getLogger(__name__)


def _amount(locale: str, units: int) -> str:
    return t("commands-budget-amount", locale, amount=units_to_usd(units))


def _status(locale: str, balance: int, budget: int) -> str:
    limit = t("commands-budget-unlimited", locale) if budget < 0 else _amount(locale, budget)
    return t("commands-budget-status", locale, balance=_amount(locale, balance), limit=limit)


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
            if not raw:
                await answer(message, bot_id, _status(locale, user.balance, user.budget))
                return
            try:
                value = int(raw)
            except ValueError:
                await answer(
                    message, bot_id, t("commands-budget-usage", locale, units=str(UNITS_PER_USD))
                )
                return
            value = max(value, -1)
            await users.set_budget(user_id, value)
        logger.info("bot=%s user=%s budget -> %s", bot_id, user_id, value)
        if value == 0:
            await answer(message, bot_id, t("commands-budget-zero", locale))
            return
        await answer(message, bot_id, _status(locale, user.balance, value))

    return router
