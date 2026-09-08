from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.session import Ctx
from unsafie.database.repositories.user import UserRepository
from unsafie.github import pat
from unsafie.pool import registry
from unsafie.scheduler.when import zone
from unsafie.settings import settings
from unsafie.ssh import binding

REMINDER = (
    "Reminder: Write ONLY executable Python code inside ```python ... ``` blocks. "
    "Do not write prose outside code blocks. Nothing written outside code blocks reaches the user. "
    "All messages must be sent via chat.send(...) inside your code. "
    "When finished, call stop() (or stop('final message')) to conclude your turn."
)


async def time_context(session: AsyncSession, ctx: Ctx) -> str:
    user = await UserRepository(session).get(ctx.user_id)
    name = user.timezone if user and user.timezone else None
    try:
        tz = zone(name or settings.default_timezone)
    except ValueError:
        tz = zone("UTC")
    now = datetime.now(UTC).astimezone(tz)
    line = f"Now: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')}), timezone {tz.key}"
    if not name:
        line += " (user timezone not set, default UTC used)"
    line += f". User locale: {ctx.locale}."
    return line


async def machines_context(ctx: Ctx) -> str:
    if not settings.pool_enabled:
        return "Pool: disabled on this server."
    mine = await registry.of_user(ctx.user_id)
    counts = await registry.counted()
    if mine:
        parts = []
        for row in mine:
            left = await registry.held(row.name)
            kept = f", held {left:.0f}s more" if left else ""
            label = f"{row.alias or row.name} ({(row.facts or {}).get('cpus', '?')} cpu{kept})"
            parts.append(label)
        head = "Your machine: " + "; ".join(parts)
    else:
        head = "Your machine: none active, the first code execution allocates one automatically"
    return f"{head}. Pool capacity: {counts.get('idle', 0)} free of {counts.get('total', 0)}."


async def accounts_context(ctx: Ctx) -> str:
    rows = await pat.accounts_of(ctx.user_id)
    if not rows:
        return "GitHub: no account attached."
    logins = ", ".join(row.login for row in rows)
    tail = " (github.use('login') switches account)" if len(rows) > 1 else ""
    return f"GitHub accounts: {logins}{tail}."


async def servers_context(ctx: Ctx) -> str:
    hosts = await binding.hosts(ctx.user_id)
    if not hosts:
        return ""
    listed = "; ".join(f"{host.alias} ({host.label})" for host in hosts)
    return f"SSH servers configured in ~/.ssh: {listed}."


async def build_context(session: AsyncSession, ctx: Ctx) -> str:
    parts = [
        await time_context(session, ctx),
        await machines_context(ctx),
        await accounts_context(ctx),
        await servers_context(ctx),
        REMINDER,
    ]
    return "\n".join(part for part in parts if part)
