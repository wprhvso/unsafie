from aiogram import Bot, Router
from aiogram.types import ChosenInlineResult, InlineQuery

from unsafie.telegram.handlers.locale import locale_for
from unsafie.telegram.inline import make_results, prompt_button

router = Router(name="inline")


def build_inline_router() -> Router:
    @router.inline_query()
    async def handle_inline_query(query: InlineQuery, bot: Bot) -> None:
        user_id = query.from_user.id
        locale = await locale_for(user_id, query.from_user)
        question = query.query.strip()
        if not question:
            await query.answer(
                results=[],
                button=prompt_button(locale),
                cache_time=0,
                is_personal=True,
            )
            return

        cards = make_results(question, locale)
        await query.answer(
            results=cards,
            cache_time=0,
            is_personal=True,
        )

    @router.chosen_inline_result()
    async def handle_chosen_inline_result(chosen: ChosenInlineResult, bot_id: int) -> None:
        if not chosen.inline_message_id or not chosen.query.strip():
            return
        from unsafie.agent.runtime import handle_inline

        await handle_inline(chosen, bot_id)

    return router
