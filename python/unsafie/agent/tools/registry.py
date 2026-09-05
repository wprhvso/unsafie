import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from claude_agent_sdk import create_sdk_mcp_server, tool

from unsafie.agent.tools.base import Handler, ToolContext

logger = logging.getLogger(__name__)

Availability = Callable[[object, ToolContext], Awaitable[bool]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Handler
    replies: bool


_REGISTRY: dict[str, list[ToolSpec]] = defaultdict(list)
_AVAILABILITY: dict[str, Availability] = {}


def register(
    server: str, name: str, description: str, input_schema: dict, *, replies: bool = False
):
    def decorator(fn: Handler) -> Handler:
        _REGISTRY[server].append(ToolSpec(name, description, input_schema, fn, replies))
        return fn

    return decorator


def available(server: str, check: Availability) -> None:
    _AVAILABILITY[server] = check


def servers() -> list[str]:
    return list(_REGISTRY)


def specs(server: str) -> list[ToolSpec]:
    return list(_REGISTRY[server])


def reply_tools() -> set[str]:
    return {f"mcp__{srv}__{s.name}" for srv, items in _REGISTRY.items() for s in items if s.replies}


async def enabled_servers(session, ctx: ToolContext) -> list[str]:
    out: list[str] = []
    for server in _REGISTRY:
        check = _AVAILABILITY.get(server)
        if check is None or await check(session, ctx):
            out.append(server)
    return out


def _bind(handler: Handler, ctx: ToolContext):
    async def run(args: dict) -> dict:
        return await handler(ctx, args)

    run.__name__ = handler.__name__
    return run


def build_server(server: str, ctx: ToolContext):
    tools = [
        tool(spec.name, spec.description, spec.input_schema)(_bind(spec.handler, ctx))
        for spec in _REGISTRY[server]
    ]
    return create_sdk_mcp_server(name=server, tools=tools)
