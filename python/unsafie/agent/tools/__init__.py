from unsafie.agent.prompt.context import register_context
from unsafie.agent.tools import gh, http, ssh, tg  # noqa: F401
from unsafie.agent.tools.base import ToolContext
from unsafie.agent.tools.gh.context import gh_available, gh_context
from unsafie.agent.tools.registry import available, build_server, enabled_servers
from unsafie.agent.tools.ssh.context import ssh_available, ssh_context

available("gh", gh_available)
available("ssh", ssh_available)
register_context("gh", gh_context)
register_context("ssh", ssh_context)


async def available_servers(session, ctx: ToolContext) -> list[str]:
    return await enabled_servers(session, ctx)


def build_servers(ctx: ToolContext, servers: list[str]) -> tuple[dict, list[str]]:
    mcp = {name: build_server(name, ctx) for name in servers}
    allowed = [f"mcp__{name}__*" for name in servers] + ["WebSearch", "WebFetch"]
    return mcp, allowed


__all__ = ["ToolContext", "available_servers", "build_server", "build_servers"]
