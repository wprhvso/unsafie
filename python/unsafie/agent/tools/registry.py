import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from unsafie.agent.tools.base import Handler, ToolContext

logger = logging.getLogger(__name__)

Availability = Callable[[object, ToolContext], Awaitable[bool]]
Context = Callable[[object, ToolContext], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    server: str
    name: str
    description: str
    input_schema: dict
    handler: Handler
    replies: bool

    @property
    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(self.input_schema.get("required") or ())


@dataclass(frozen=True)
class Server:
    name: str
    available: Availability | None = None
    context: Context | None = None


_TOOLS: dict[str, list[ToolSpec]] = defaultdict(list)
_SERVERS: dict[str, Server] = {}


def register(
    server: str, name: str, description: str, input_schema: dict, *, replies: bool = False
):
    def decorator(fn: Handler) -> Handler:
        _TOOLS[server].append(ToolSpec(server, name, description, input_schema, fn, replies))
        return fn

    return decorator


def declare(name: str, *, available: Availability | None = None, context: Context | None = None):
    _SERVERS[name] = Server(name, available, context)


def servers() -> list[str]:
    return list(_TOOLS)


def specs(server: str) -> list[ToolSpec]:
    return list(_TOOLS[server])


async def enabled(session, ctx: ToolContext) -> list[str]:
    out: list[str] = []
    for name in _TOOLS:
        server = _SERVERS.get(name)
        if server is None or server.available is None or await server.available(session, ctx):
            out.append(name)
    return out


async def context_for(session, ctx: ToolContext, names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        server = _SERVERS.get(name)
        if server is None or server.context is None:
            continue
        text = await server.context(session, ctx)
        if text:
            out.append(text)
    return out


def build_tools(ctx: ToolContext, names: list[str]) -> tuple[list[dict], dict[str, ToolSpec]]:
    definitions: list[dict] = []
    tools: dict[str, ToolSpec] = {}
    for name in names:
        for spec in _TOOLS[name]:
            clash = tools.get(spec.name)
            if clash is not None:
                raise RuntimeError(
                    f"tool {spec.name} is registered by both {clash.server} and {name}"
                )
            tools[spec.name] = spec
            definitions.append(spec.definition)
    return definitions, tools
