from typing import Annotated

from fastapi import Depends

from yet_another_claude_bot.api.dependencies.database import Session
from yet_another_claude_bot.api.services.bot import BotService


def get_bot_service(session: Session) -> BotService:
    return BotService(session)


BotServiceDep = Annotated[BotService, Depends(get_bot_service)]
