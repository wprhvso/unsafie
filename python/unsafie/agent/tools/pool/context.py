import logging

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.tools.base import ToolContext
from unsafie.pool import registry
from unsafie.settings import settings

logger = logging.getLogger(__name__)

SERVER = "pool"

CHEATSHEET = (
    "unsafie CLI on the machine: say file page note | machines take release run fan job | "
    "repo clone github gh | chrome (start goto click type shot text md eval tabs) | "
    "blob kv secret | schedule watch sub tz | fetch fs doctor. "
    "`unsafie help --json` is the whole index in one call."
)


async def pool_available(session: AsyncSession, ctx: ToolContext) -> bool:
    return settings.pool_enabled


async def pool_context(session: AsyncSession, ctx: ToolContext) -> str:
    mine = await registry.of_user(ctx.user_id)
    counts = await registry.counted()
    if mine:
        held = "; ".join(
            f"{m.alias or m.name} ({m.profile}, {(m.facts or {}).get('cpus', '?')} cpu)" for m in mine
        )
        line = f"Pool machines: {held}"
    else:
        line = "Pool machines: none yet — the first command takes one automatically"
    lines = [
        line,
        f"  {counts.get('idle', 0)} free of {counts.get('total', 0)} in the pool. "
        f"A machine is single use: `unsafie release` destroys it, and it never comes back. "
        f"Push to git or `unsafie blob put` anything worth keeping.",
        f"  {CHEATSHEET}",
    ]
    return "\n".join(lines)
