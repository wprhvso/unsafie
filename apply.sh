#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="."
if [ -d "python/unsafie" ]; then
    BASE_DIR="python"
fi

cat << 'EOF' > "${BASE_DIR}/unsafie/agent/session.py"
from dataclasses import dataclass
from uuid import UUID

from aiogram import Bot

from unsafie.database import SessionLocal
from unsafie.database.models.turn import Turn
from unsafie.database.repositories.turn import TurnRepository


@dataclass(frozen=True)
class Ctx:
    bot: Bot
    bot_id: int
    chat_id: int
    user_id: int
    turn_id: UUID
    locale: str = "en"
    inline_message_id: str | None = None
    machine_name: str | None = None

    @property
    def prefix(self) -> str:
        return f"bot={self.bot_id} chat={self.chat_id} user={self.user_id} turn={self.turn_id}"

    @property
    def session_id(self) -> str:
        return str(self.turn_id)

    @property
    def name(self) -> str:
        return self.machine_name or "sandbox"


async def current_turn(ctx: Ctx) -> Turn | None:
    async with SessionLocal() as session:
        return await TurnRepository(session).get(ctx.turn_id)
EOF

python3 - << EOF
from pathlib import Path

target = Path("${BASE_DIR}/unsafie/agent/loop.py")
content = target.read_text(encoding="utf-8")

old = """    clear_contextvars()
    bind_contextvars(
        turn_id=ctx.turn_id,
        session_id=ctx.session_id,
        bot_id=ctx.bot_id,
        chat_id=ctx.chat_id,
        user_id=ctx.user_id,
        agent_name=ctx.name,
        model=model,
    )"""

new = """    clear_contextvars()
    bind_contextvars(
        turn_id=str(ctx.turn_id),
        bot_id=ctx.bot_id,
        chat_id=ctx.chat_id,
        user_id=ctx.user_id,
        model=model,
    )"""

if old in content:
    target.write_text(content.replace(old, new, 1), encoding="utf-8")
EOF
