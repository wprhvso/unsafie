import logging

from sqlalchemy.ext.asyncio import AsyncSession

from unsafie.agent.tools.base import ToolContext
from unsafie.database.repositories.ssh import SshRepository

logger = logging.getLogger(__name__)

SERVER = "ssh"


async def ssh_available(session: AsyncSession, ctx: ToolContext) -> bool:
    return bool(await SshRepository(session).hosts(ctx.user_id))


async def ssh_context(session: AsyncSession, ctx: ToolContext) -> str:
    hosts = await SshRepository(session).hosts(ctx.user_id)
    if not hosts:
        return ""
    lines = ["SSH servers: " + "; ".join(f"{h.alias} ({h.label})" for h in hosts)]
    lines.append("  Tools take host= as an alias; the default is the only server.")
    return "\n".join(lines)
