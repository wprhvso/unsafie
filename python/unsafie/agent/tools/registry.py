import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from unsafie.agent.tools.base import Handler, ToolContext

logger = logging.getLogger(__name__)

Availability = Callable[[object, ToolContext], Awaitable[bool]]


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
class Bound:
    spec: ToolSpec
    run: Callable[[dict], Awaitable[dict]]

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def replies(self) -> bool:
        return self.spec.replies

    @property
    def required(self) -> tuple[str, ...]:
        return self.spec.required


_REGISTRY: dict[str, list[ToolSpec]] = defaultdict(list)
_AVAILABILITY: dict[str, Availability] = {}


def register(
    server: str, name: str, description: str, input_schema: dict, *, replies: bool = False
):
    def decorator(fn: Handler) -> Handler:
        _REGISTRY[server].append(
            ToolSpec(server, name, description, input_schema, fn, replies)
        )
        return fn

    return decorator


def available(server: str, check: Availability) -> None:
    _AVAILABILITY[server] = check


def servers() -> list[str]:
    return list(_REGISTRY)


def specs(server: str) -> list[ToolSpec]:
    return list(_REGISTRY[server])


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


def build_tools(ctx: ToolContext, servers: list[str]) -> tuple[list[dict], dict[str, Bound]]:
    definitions: list[dict] = []
    bound: dict[str, Bound] = {}
    for server in servers:
        for spec in _REGISTRY[server]:
            clash = bound.get(spec.name)
            if clash is not None:
                raise RuntimeError(
                    f"tool {spec.name} is registered by both {clash.spec.server} and {server}"
                )
            bound[spec.name] = Bound(spec, _bind(spec.handler, ctx))
            definitions.append(spec.definition)
    return definitions, bound
