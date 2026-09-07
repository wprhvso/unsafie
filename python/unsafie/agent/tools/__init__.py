from unsafie.agent.tools import gh, http, ssh, tg  # noqa: F401
from unsafie.agent.tools.base import ToolContext
from unsafie.agent.tools.gh.context import gh_available, gh_context
from unsafie.agent.tools.registry import ToolSpec, build_tools, declare, enabled
from unsafie.agent.tools.ssh.context import ssh_available, ssh_context

declare("gh", available=gh_available, context=gh_context)
declare("ssh", available=ssh_available, context=ssh_context)

__all__ = ["ToolContext", "ToolSpec", "build_tools", "enabled"]
