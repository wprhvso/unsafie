import json
import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.registry import register
from unsafie.database import SessionLocal
from unsafie.database.repositories.subscription import SubscriptionRepository
from unsafie.github import subscriptions
from unsafie.github.errors import GithubError, NotFound

logger = logging.getLogger(__name__)


@register(
    SERVER,
    "sub_list",
    "Repository event subscriptions of this chat: what arrives here and with what filters.",
    schema([]),
)
@guarded
async def sub_list(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        rows = await SubscriptionRepository(session).for_chat(ctx.bot_id, ctx.chat_id)
    if not rows:
        return text("no subscriptions in this chat. Kinds: " + " | ".join(subscriptions.KINDS))
    return text(subscriptions.summary(rows, ctx.locale))


@register(
    SERVER,
    "sub_add",
    "Subscribe this chat to repository events. kind = ci | push | pr | pr_comments | issues | "
    "issue_comments | releases | deploys | stars | admin | mentions | all. "
    'filters — a JSON object: {"branch": "main", "author": "vasya", "label": "bug", '
    '"workflow": "ci", "only_failures": true, "ignore_self": true}. '
    "Notifications arrive over webhooks, so the app must be installed on the repository.",
    schema(["kind"], kind=str, filters=str, repo=str),
)
@guarded
async def sub_add(ctx: ToolContext, args: dict) -> dict:
    kind = (args["kind"] or "").strip().lower()
    if not subscriptions.valid_kind(kind):
        raise GithubError("kind must be one of " + " | ".join(subscriptions.KINDS))
    filters: dict = {}
    if raw := args.get("filters"):
        try:
            filters = json.loads(raw)
        except ValueError as e:
            raise GithubError(f"filters is not JSON: {e}") from None
        if not isinstance(filters, dict):
            raise GithubError("filters must be a JSON object")
        unknown = set(filters) - set(subscriptions.FILTERS)
        if unknown:
            raise GithubError(
                f"unknown filters: {', '.join(sorted(unknown))}. Available: {', '.join(subscriptions.FILTERS)}"
            )
    state = await session_for(ctx, args)
    async with SessionLocal() as session:
        repo = SubscriptionRepository(session)
        existing = await repo.for_chat(ctx.bot_id, ctx.chat_id)
        for sub, bound in existing:
            if bound.id == state.repo.id and sub.kind == kind:
                raise GithubError(f"already subscribed: [{sub.id}] {bound.full} · {kind}")
        created = await repo.add(ctx.bot_id, ctx.chat_id, ctx.user_id, state.repo.id, kind, filters)
    return text(f"subscribed [{created.id}]: {state.repo.full} · {kind}")


@register(
    SERVER,
    "sub_remove",
    "Unsubscribe: id from sub_list, or all=true to remove every subscription of this chat.",
    schema([], id=int, all=bool),
)
@guarded
async def sub_remove(ctx: ToolContext, args: dict) -> dict:
    async with SessionLocal() as session:
        repo = SubscriptionRepository(session)
        if args.get("all"):
            n = await repo.remove_all(ctx.bot_id, ctx.chat_id)
            return text(f"{n} subscription(s) removed")
        if not args.get("id"):
            raise GithubError("id or all=true is required")
        if not await repo.remove(ctx.bot_id, ctx.chat_id, int(args["id"])):
            raise NotFound(f"no subscription [{args['id']}] in this chat")
    return text(f"subscription [{args['id']}] removed")
