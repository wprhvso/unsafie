import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, each_user_client, user_client
from unsafie.agent.tools.gh.format import issue_line
from unsafie.agent.tools.registry import register

logger = logging.getLogger(__name__)

PRESETS = {
    "my_prs": "is:pr is:open author:{login}",
    "review_requested": "is:pr is:open review-requested:{login}",
    "assigned": "is:open assignee:{login}",
    "mentioned": "is:open mentions:{login}",
    "my_issues": "is:issue is:open author:{login}",
}


@register(
    SERVER,
    "gh_search_issues",
    "Search issues and pull requests across GitHub on behalf of the user's connected accounts. "
    "preset = my_prs | review_requested | assigned | mentioned | my_issues, or a raw query in "
    "GitHub syntax ('repo:acme/api is:open label:bug'). Runs across every connected account and "
    "merges the results.",
    schema([], query=str, preset=str, limit=int, account=str),
)
@guarded
async def gh_search_issues(ctx: ToolContext, args: dict) -> dict:
    limit = max(1, min(int(args.get("limit") or 25), 50))
    preset = (args.get("preset") or "").strip()
    if preset and preset not in PRESETS:
        return text("preset must be one of " + " | ".join(PRESETS))
    if not preset and not args.get("query"):
        return text("query or preset is required")
    lines: list[str] = []
    problems: list[str] = []
    seen: set[str] = set()
    if account := args.get("account"):
        clients = [(await user_client(ctx.user_id, account), None)]
    else:
        clients = [pair async for pair in each_user_client(ctx.user_id)]
    for client, problem in clients:
        if client is None:
            problems.append(f"{problem[0]}: {problem[1]}")
            continue
        query = PRESETS[preset].format(login=client.login) if preset else args["query"]
        items = await client.search_issues(query, limit=limit)
        for item in items:
            url = item.get("html_url") or ""
            if url in seen:
                continue
            seen.add(url)
            repo = "/".join(url.split("/")[3:5]) if url else ""
            lines.append(f"{issue_line(item)} · {repo}\n  {url}")
    body = "\n".join(lines[:limit]) if lines else "nothing found"
    if problems:
        body += "\n\nunavailable accounts:\n" + "\n".join(problems)
    return text(body)


@register(
    SERVER,
    "gh_notifications",
    "The user's GitHub notifications (the bell): what is unread and why. all=true includes read ones. "
    "mark — thread id to mark as read.",
    schema([], all=bool, limit=int, account=str, mark=str),
)
@guarded
async def gh_notifications(ctx: ToolContext, args: dict) -> dict:
    if mark := args.get("mark"):
        client = await user_client(ctx.user_id, args.get("account"))
        await client.mark_notification(mark)
        return text(f"thread {mark} marked as read")
    limit = max(1, min(int(args.get("limit") or 30), 50))
    lines: list[str] = []
    problems: list[str] = []
    async for client, problem in each_user_client(ctx.user_id):
        if client is None:
            problems.append(f"{problem[0]}: {problem[1]}")
            continue
        items = await client.notifications(bool(args.get("all")), limit)
        for item in items:
            subject = item.get("subject") or {}
            repo = (item.get("repository") or {}).get("full_name")
            lines.append(
                f"[{item.get('id')}] {repo} · {subject.get('type')} · {item.get('reason')}\n  {subject.get('title')}"
            )
    body = "\n".join(lines[:limit]) if lines else "no notifications"
    if problems:
        body += "\n\nunavailable accounts:\n" + "\n".join(problems)
    return text(body)
