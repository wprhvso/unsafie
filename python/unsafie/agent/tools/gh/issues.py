import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import comment_block, issue_line
from unsafie.agent.tools.registry import register
from unsafie.github.errors import GithubError

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str)


def _list(values: str | None) -> list[str] | None:
    if not values:
        return None
    return [v.strip() for v in values.split(",") if v.strip()]


@register(
    SERVER,
    "issue_list",
    "Issues of a repository: state = open (default) | closed | all, labels — comma-separated, limit.",
    schema([], state=str, labels=str, limit=int, **REPO_ARGS),
)
@guarded
async def issue_list(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    items = await state.client.issues(
        args.get("state") or "open",
        args.get("labels"),
        max(1, min(int(args.get("limit") or 30), 100)),
    )
    if not items:
        return text(f"no issues in {state.repo.full}")
    return text(f"{state.repo.full}:\n" + "\n".join(issue_line(i) for i in items))


@register(
    SERVER,
    "issue_get",
    "One issue with its body and comments: number.",
    schema(["number"], number=int, comments=bool, **REPO_ARGS),
)
@guarded
async def issue_get(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    number = int(args["number"])
    issue = await state.client.issue(number)
    lines = [
        issue_line(issue),
        f"{issue.get('html_url')}",
        "",
        issue.get("body") or "(no description)",
    ]
    if args.get("comments", True):
        comments = await state.client.comments(number)
        if comments:
            lines += ["", f"--- {len(comments)} comment(s) ---"]
            lines += [comment_block(c) for c in comments]
    return text("\n".join(lines)[:60_000])


@register(
    SERVER,
    "issue_create",
    "Create an issue: title, body (markdown), labels and assignees comma-separated.",
    schema(["title"], title=str, body=str, labels=str, assignees=str, **REPO_ARGS),
)
@guarded
async def issue_create(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    issue = await state.client.create_issue(
        args["title"], args.get("body"), _list(args.get("labels")), _list(args.get("assignees"))
    )
    return text(f"created issue #{issue['number']}: {issue['html_url']}")


@register(
    SERVER,
    "issue_update",
    "Change an issue: title, body, state (open|closed), labels (replaces the set), assignees, milestone.",
    schema(
        ["number"],
        number=int,
        title=str,
        body=str,
        state=str,
        labels=str,
        assignees=str,
        **REPO_ARGS,
    ),
)
@guarded
async def issue_update(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    fields: dict = {}
    for key in ("title", "body", "state"):
        if args.get(key) is not None:
            fields[key] = args[key]
    if labels := _list(args.get("labels")):
        fields["labels"] = labels
    if assignees := _list(args.get("assignees")):
        fields["assignees"] = assignees
    if not fields:
        raise GithubError("nothing to change")
    issue = await state.client.update_issue(int(args["number"]), **fields)
    return text(f"issue #{issue['number']} updated: " + ", ".join(fields))


@register(
    SERVER,
    "issue_comment",
    "Comment on an issue or a pull request (they share numbering): number, body. "
    "comment_id + body edits an existing comment; comment_id + delete=true removes it.",
    schema([], number=int, body=str, comment_id=int, delete=bool, **REPO_ARGS),
)
@guarded
async def issue_comment(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    if comment_id := args.get("comment_id"):
        if args.get("delete"):
            await state.client.delete_comment(int(comment_id))
            return text(f"comment {comment_id} deleted")
        if not args.get("body"):
            raise GithubError("body is required")
        updated = await state.client.update_comment(int(comment_id), args["body"])
        return text(f"comment {comment_id} edited: {updated.get('html_url')}")
    if not args.get("number") or not args.get("body"):
        raise GithubError("number and body are required")
    created = await state.client.comment(int(args["number"]), args["body"])
    return text(f"commented on #{args['number']}: {created.get('html_url')}")


@register(
    SERVER,
    "issue_labels",
    "Labels: without arguments — the repository's list; number + add / remove — change the labels of an issue.",
    schema([], number=int, add=str, remove=str, **REPO_ARGS),
)
@guarded
async def issue_labels(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    number = args.get("number")
    if number and (add := _list(args.get("add"))):
        await state.client.add_labels(int(number), add)
        return text(f"added to #{number}: " + ", ".join(add))
    if number and (remove := _list(args.get("remove"))):
        for label in remove:
            await state.client.remove_label(int(number), label)
        return text(f"removed from #{number}: " + ", ".join(remove))
    labels = await state.client.labels()
    return text(
        f"{state.repo.full} labels:\n"
        + "\n".join(f"{x['name']} — {x.get('description') or ''}" for x in labels)
    )
