from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.tools.base import ToolContext
from unsafie.database.repositories.user import UserRepository
from unsafie.scheduler.when import zone
from unsafie.settings import settings

_PROVIDERS: dict[str, object] = {}


def register_context(server: str, provider) -> None:
    _PROVIDERS[server] = provider


async def time_context(session: AsyncSession, ctx: ToolContext) -> str:
    user = await UserRepository(session).get(ctx.user_id)
    name = user.timezone if user and user.timezone else None
    try:
        tz = zone(name or settings.default_timezone)
    except ValueError:
        tz = zone("UTC")
    now = datetime.now(UTC).astimezone(tz)
    line = f"Now: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')}), timezone {tz.key}"
    if not name:
        line += (
            " (the user has not set one; ask and save it via timezone_set when time of day matters)"
        )
    line += f". User locale: {ctx.locale}."
    return line


async def build_context(session: AsyncSession, ctx: ToolContext, servers: list[str]) -> str:
    parts = [await time_context(session, ctx)]
    for server in servers:
        provider = _PROVIDERS.get(server)
        if provider is None:
            continue
        text = await provider(session, ctx)
        if text:
            parts.append(text)
    return "\n".join(parts)
