import logging

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import comment_block, commit_line, pull_line
from unsafie.agent.tools.registry import register
from unsafie.github import workspace
from unsafie.github.errors import GithubError

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str)
MERGE_METHODS = ("merge", "squash", "rebase")


@register(
    SERVER,
    "pr_list",
    "Pull requests: state = open (default) | closed | all, limit.",
    schema([], state=str, limit=int, **REPO_ARGS),
)
@guarded
async def pr_list(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    items = await state.client.pulls(
        args.get("state") or "open", max(1, min(int(args.get("limit") or 30), 100))
    )
    if not items:
        return text(f"no pull requests in {state.repo.full}")
    return text(f"{state.repo.full}:\n" + "\n".join(pull_line(p) for p in items))


@register(
    SERVER,
    "pr_get",
    "One pull request: description, commits, changed files, reviews and comments.",
    schema(["number"], number=int, files=bool, comments=bool, **REPO_ARGS),
)
@guarded
async def pr_get(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    number = int(args["number"])
    pr = await state.client.pull(number)
    lines = [
        pull_line(pr),
        pr.get("html_url") or "",
        f"mergeable: {pr.get('mergeable')} ({pr.get('mergeable_state')}), "
        f"+{pr.get('additions')}/-{pr.get('deletions')} in {pr.get('changed_files')} file(s)",
        "",
        pr.get("body") or "(no description)",
    ]
    commits = await state.client.pull_commits(number)
    if commits:
        lines += ["", f"--- {len(commits)} commit(s) ---", *[commit_line(c) for c in commits[:30]]]
    if args.get("files", True):
        files = await state.client.pull_files(number)
        lines += ["", f"--- {len(files)} file(s) ---"]
        lines += [
            f"{f['status']} {f['filename']} (+{f['additions']}/-{f['deletions']})"
            for f in files[:50]
        ]
    if args.get("comments", True):
        reviews = await state.client.reviews(number)
        if reviews:
            lines += ["", "--- reviews ---"]
            lines += [
                f"{r.get('state')} by {(r.get('user') or {}).get('login')}: {r.get('body') or ''}"
                for r in reviews
            ]
        comments = await state.client.comments(number)
        if comments:
            lines += [
                "",
                f"--- {len(comments)} comment(s) ---",
                *[comment_block(c) for c in comments],
            ]
    return text("\n".join(lines)[:60_000])


@register(
    SERVER,
    "pr_diff",
    "The diff of a pull request as a unified patch. path — limit to one file.",
    schema(["number"], number=int, path=str, **REPO_ARGS),
)
@guarded
async def pr_diff(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    number = int(args["number"])
    if path := args.get("path"):
        files = await state.client.pull_files(number)
        for f in files:
            if f["filename"] == path:
                return text(f"--- {path}\n{f.get('patch') or '(binary or too large)'}")
        raise GithubError(f"{path} is not among the changed files of #{number}")
    diff = await state.client.pull_diff(number)
    if len(diff) > 60_000:
        diff = diff[:60_000] + "\n…(truncated, ask for one path)"
    return text(diff)


@register(
    SERVER,
    "pr_create",
    "Create a pull request: title, head — the source branch (the worktree branch by default), "
    "base — the target branch (the default branch by default), body, draft.",
    schema(["title"], title=str, head=str, base=str, body=str, draft=bool, repo=str, branch=str),
)
@guarded
async def pr_create(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    head = args.get("head") or state.branch
    base = args.get("base") or await workspace.default_branch(state.repo, state.client)
    if head == base:
        raise GithubError(f"head and base are the same branch ({head}); create a branch first")
    pr = await state.client.create_pull(
        args["title"], head, base, args.get("body"), bool(args.get("draft"))
    )
    return text(f"created PR #{pr['number']} {head} → {base}: {pr['html_url']}")


@register(
    SERVER,
    "pr_update",
    "Change a pull request: title, body, base, state (open|closed), draft=false to mark ready.",
    schema(
        ["number"], number=int, title=str, body=str, base=str, state=str, draft=bool, **REPO_ARGS
    ),
)
@guarded
async def pr_update(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    fields = {k: args[k] for k in ("title", "body", "base", "state") if args.get(k) is not None}
    if not fields:
        raise GithubError("nothing to change")
    pr = await state.client.update_pull(int(args["number"]), **fields)
    return text(f"PR #{pr['number']} updated: " + ", ".join(fields))


@register(
    SERVER,
    "pr_merge",
    "Merge a pull request: method = merge (default) | squash | rebase, title/message for the commit. "
    "Only at an explicit request of the user.",
    schema(
        ["number"], number=int, method=str, title=str, message=str, delete_branch=bool, **REPO_ARGS
    ),
)
@guarded
async def pr_merge(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    method = (args.get("method") or "merge").lower()
    if method not in MERGE_METHODS:
        raise GithubError("method must be one of " + " | ".join(MERGE_METHODS))
    number = int(args["number"])
    pr = await state.client.pull(number)
    result = await state.client.merge_pull(number, method, args.get("title"), args.get("message"))
    out = f"PR #{number} merged ({method}): `{(result.get('sha') or '')[:7]}`"
    if args.get("delete_branch"):
        branch = (pr.get("head") or {}).get("ref")
        if branch:
            await state.client.delete_ref(branch)
            out += f", branch `{branch}` deleted"
    return text(out)


@register(
    SERVER,
    "pr_review",
    "Review a pull request: event = APPROVE | REQUEST_CHANGES | COMMENT, body — the text. "
    "reviewers — comma-separated logins to request a review from instead.",
    schema(["number"], number=int, event=str, body=str, reviewers=str, **REPO_ARGS),
)
@guarded
async def pr_review(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    number = int(args["number"])
    if raw := args.get("reviewers"):
        reviewers = [r.strip().lstrip("@") for r in raw.split(",") if r.strip()]
        await state.client.request_reviewers(number, reviewers)
        return text(f"review requested from {', '.join(reviewers)} on #{number}")
    event = (args.get("event") or "COMMENT").upper()
    if event not in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        raise GithubError("event must be APPROVE | REQUEST_CHANGES | COMMENT")
    review = await state.client.review(number, event, args.get("body"), None)
    return text(f"review {event} submitted on #{number}: {review.get('html_url')}")
