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
    "Reminder: nothing you write as text is delivered. Only say(), file() and page(), called "
    "from inside a python tool call, reach the chat. Do not end this turn until a call has run "
    "say(...) with the answer."
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
        line += (
            " (the user has not set one; ask and save it with automation.timezone(...) when the "
            "time of day matters)"
        )
    line += f". User locale: {ctx.locale}."
    return line


async def machines_context(ctx: Ctx) -> str:
    if not settings.pool_enabled:
        return "Pool: switched off on this server — no machine, so python calls will not run."
    mine = await registry.of_user(ctx.user_id)
    counts = await registry.counted()
    if mine:
        held = "; ".join(
            f"{row.alias or row.name} ({(row.facts or {}).get('cpus', '?')} cpu)" for row in mine
        )
        head = f"Your machine: {held}"
    else:
        head = "Your machine: none yet — the first python call takes one automatically"
    return (
        f"{head}. Pool: {counts.get('idle', 0)} free of {counts.get('total', 0)}, every machine "
        "fully equipped. A machine is single use: releasing destroys it, and its files go with it."
    )


async def accounts_context(ctx: Ctx) -> str:
    rows = await pat.accounts_of(ctx.user_id)
    if not rows:
        return "GitHub: no account attached — the user adds one with /gh <token>."
    logins = ", ".join(row.login for row in rows)
    tail = " · github.use('login') switches between them" if len(rows) > 1 else ""
    return f"GitHub accounts: {logins}{tail}."


async def servers_context(ctx: Ctx) -> str:
    hosts = await binding.hosts(ctx.user_id)
    if not hosts:
        return ""
    listed = "; ".join(f"{host.alias} ({host.label})" for host in hosts)
    return (
        f"SSH servers: {listed}. The private key of this user is already on the machine, so plain "
        "ssh works; ssh.run(cmd, host) goes through the server instead."
    )


async def build_context(session: AsyncSession, ctx: Ctx) -> str:
    parts = [
        await time_context(session, ctx),
        await machines_context(ctx),
        await accounts_context(ctx),
        await servers_context(ctx),
        REMINDER,
    ]
    return "\n".join(part for part in parts if part)
