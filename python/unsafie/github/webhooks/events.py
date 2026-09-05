import logging

from unsafie.github import icons
from unsafie.mime import human_size

logger = logging.getLogger(__name__)

MAX_BODY = 400


def _short(text: str | None, limit: int = MAX_BODY) -> str:
    text = (text or "").strip().replace("\r", "")
    if not text:
        return ""
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _who(payload: dict) -> str:
    return (payload.get("sender") or {}).get("login") or "someone"


def _repo(payload: dict) -> str:
    return (payload.get("repository") or {}).get("full_name") or "?"


def _link(url: str | None, label: str) -> str:
    return f"[{label}]({url})" if url else label


def push(payload: dict) -> str | None:
    ref = (payload.get("ref") or "").removeprefix("refs/heads/")
    commits = payload.get("commits") or []
    if payload.get("deleted"):
        return f"{icons.EVENT['delete']} **{_repo(payload)}** branch `{ref}` deleted by {_who(payload)}"
    if not commits and not payload.get("created"):
        return None
    head = payload.get("head_commit") or {}
    lines = [
        f"{icons.EVENT['push']} **{_repo(payload)}** `{ref}` — {len(commits)} commit(s) by {_who(payload)}"
    ]
    for c in commits[:5]:
        lines.append(
            f"· `{(c.get('id') or '')[:7]}` {_short(c.get('message', '').split(chr(10))[0], 120)}"
        )
    if len(commits) > 5:
        lines.append(f"· …and {len(commits) - 5} more")
    if url := (head.get("url") or payload.get("compare")):
        lines.append(_link(url, "diff"))
    return "\n".join(lines)


def pull_request(payload: dict) -> str | None:
    action = payload.get("action")
    if action not in ("opened", "closed", "reopened", "ready_for_review", "converted_to_draft"):
        return None
    pr = payload.get("pull_request") or {}
    verb = "merged" if (action == "closed" and pr.get("merged")) else action.replace("_", " ")
    head = f"{icons.pull_state(pr)} **{_repo(payload)}** PR #{pr.get('number')} {verb} by {_who(payload)}"
    body = [head, _link(pr.get("html_url"), pr.get("title") or "")]
    if action == "opened":
        base = (pr.get("base") or {}).get("ref")
        branch = (pr.get("head") or {}).get("ref")
        body.append(f"`{branch}` → `{base}`, +{pr.get('additions', 0)}/-{pr.get('deletions', 0)}")
        if summary := _short(pr.get("body"), 300):
            body.append(summary)
    return "\n".join(x for x in body if x)


def issues(payload: dict) -> str | None:
    action = payload.get("action")
    if action not in ("opened", "closed", "reopened", "assigned", "labeled"):
        return None
    issue = payload.get("issue") or {}
    state = icons.STATE.get(issue.get("state") or "open", "📌")
    lines = [
        f"{state} **{_repo(payload)}** issue #{issue.get('number')} {action} by {_who(payload)}",
        _link(issue.get("html_url"), issue.get("title") or ""),
    ]
    if action == "opened" and (summary := _short(issue.get("body"), 300)):
        lines.append(summary)
    if action == "labeled" and (label := payload.get("label")):
        lines.append(f"label: `{label.get('name')}`")
    return "\n".join(lines)


def issue_comment(payload: dict) -> str | None:
    if payload.get("action") != "created":
        return None
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    what = "PR" if issue.get("pull_request") else "issue"
    return "\n".join(
        [
            f"{icons.EVENT['issue_comment']} **{_repo(payload)}** comment on {what} #{issue.get('number')} by {_who(payload)}",
            _link(comment.get("html_url"), issue.get("title") or ""),
            _short(comment.get("body")),
        ]
    )


def pull_request_review(payload: dict) -> str | None:
    if payload.get("action") != "submitted":
        return None
    review = payload.get("review") or {}
    pr = payload.get("pull_request") or {}
    state = {"approved": "✅", "changes_requested": "🛠", "commented": "💬"}.get(
        (review.get("state") or "").lower(), "🔍"
    )
    return "\n".join(
        x
        for x in [
            f"{state} **{_repo(payload)}** review on PR #{pr.get('number')} by {_who(payload)}: {review.get('state')}",
            _link(review.get("html_url"), pr.get("title") or ""),
            _short(review.get("body")),
        ]
        if x
    )


def pull_request_review_comment(payload: dict) -> str | None:
    if payload.get("action") != "created":
        return None
    comment = payload.get("comment") or {}
    pr = payload.get("pull_request") or {}
    return "\n".join(
        x
        for x in [
            f"{icons.EVENT['pull_request_review_comment']} **{_repo(payload)}** review comment on PR #{pr.get('number')} by {_who(payload)}",
            f"`{comment.get('path')}`",
            _link(comment.get("html_url"), pr.get("title") or ""),
            _short(comment.get("body")),
        ]
        if x
    )


def workflow_run(payload: dict) -> str | None:
    if payload.get("action") != "completed":
        return None
    run = payload.get("workflow_run") or {}
    mark = icons.conclusion(run.get("conclusion"))
    lines = [
        f"{mark} **{_repo(payload)}** {run.get('name')} on `{run.get('head_branch')}`: {run.get('conclusion')}",
        _link(run.get("html_url"), f"run #{run.get('run_number')}"),
    ]
    if commit := (run.get("head_commit") or {}).get("message"):
        lines.append(f"`{(run.get('head_sha') or '')[:7]}` {_short(commit.splitlines()[0], 120)}")
    if run.get("conclusion") not in ("success", "skipped", "cancelled"):
        lines.append("Use actions_jobs / actions_logs to see what failed.")
    return "\n".join(lines)


def check_suite(payload: dict) -> str | None:
    if payload.get("action") != "completed":
        return None
    suite = payload.get("check_suite") or {}
    if (suite.get("conclusion") or "success") == "success":
        return None
    return (
        f"{icons.conclusion(suite.get('conclusion'))} **{_repo(payload)}** checks on "
        f"`{suite.get('head_branch')}`: {suite.get('conclusion')}"
    )


def release(payload: dict) -> str | None:
    if payload.get("action") not in ("published", "released"):
        return None
    rel = payload.get("release") or {}
    return "\n".join(
        x
        for x in [
            f"{icons.EVENT['release']} **{_repo(payload)}** release {rel.get('tag_name')} by {_who(payload)}",
            _link(rel.get("html_url"), rel.get("name") or rel.get("tag_name") or ""),
            _short(rel.get("body"), 300),
        ]
        if x
    )


def create(payload: dict) -> str | None:
    if payload.get("ref_type") != "tag":
        return None
    return f"{icons.EVENT['create']} **{_repo(payload)}** tag `{payload.get('ref')}` created by {_who(payload)}"


def delete(payload: dict) -> str | None:
    return (
        f"{icons.EVENT['delete']} **{_repo(payload)}** {payload.get('ref_type')} "
        f"`{payload.get('ref')}` deleted by {_who(payload)}"
    )


def deployment_status(payload: dict) -> str | None:
    status = payload.get("deployment_status") or {}
    state = status.get("state")
    if state not in ("success", "failure", "error"):
        return None
    mark = "🚀" if state == "success" else "❌"
    env = (payload.get("deployment") or {}).get("environment")
    return f"{mark} **{_repo(payload)}** deploy to `{env}`: {state}"


def star(payload: dict) -> str | None:
    if payload.get("action") != "created":
        return None
    count = (payload.get("repository") or {}).get("stargazers_count")
    return f"{icons.EVENT['star']} **{_repo(payload)}** starred by {_who(payload)} ({count} total)"


def fork(payload: dict) -> str | None:
    forkee = payload.get("forkee") or {}
    return f"{icons.EVENT['fork']} **{_repo(payload)}** forked by {_who(payload)} → {forkee.get('full_name')}"


def member(payload: dict) -> str | None:
    return (
        f"{icons.EVENT['member']} **{_repo(payload)}** collaborator "
        f"{(payload.get('member') or {}).get('login')} {payload.get('action')} by {_who(payload)}"
    )


def repository(payload: dict) -> str | None:
    action = payload.get("action")
    if action not in (
        "created",
        "deleted",
        "archived",
        "renamed",
        "transferred",
        "publicized",
        "privatized",
    ):
        return None
    return (
        f"{icons.EVENT['repository']} **{_repo(payload)}** repository {action} by {_who(payload)}"
    )


def public(payload: dict) -> str | None:
    return f"{icons.EVENT['public']} **{_repo(payload)}** is now public"


def workflow_job(payload: dict) -> str | None:
    job = payload.get("workflow_job") or {}
    if payload.get("action") != "completed" or job.get("conclusion") in (
        "success",
        "skipped",
        None,
    ):
        return None
    return (
        f"{icons.conclusion(job.get('conclusion'))} **{_repo(payload)}** job "
        f"`{job.get('name')}`: {job.get('conclusion')} — {_link(job.get('html_url'), 'logs')}"
    )


FORMATTERS = {
    "push": push,
    "pull_request": pull_request,
    "issues": issues,
    "issue_comment": issue_comment,
    "pull_request_review": pull_request_review,
    "pull_request_review_comment": pull_request_review_comment,
    "workflow_run": workflow_run,
    "workflow_job": workflow_job,
    "check_suite": check_suite,
    "release": release,
    "create": create,
    "delete": delete,
    "deployment_status": deployment_status,
    "star": star,
    "fork": fork,
    "member": member,
    "repository": repository,
    "public": public,
}


def render(event: str, payload: dict) -> str | None:
    formatter = FORMATTERS.get(event)
    if formatter is None:
        return None
    try:
        return formatter(payload)
    except Exception:
        logger.exception("failed to render %s", event)
        return None


def render_mention(event: str, payload: dict, login: str) -> str:
    base = render(event, payload) or f"**{_repo(payload)}** {event} by {_who(payload)}"
    return f"{icons.EVENT['mention']} @{login} mentioned\n{base}"


def artifact_line(item: dict) -> str:
    return f"{item.get('name')} ({human_size(item.get('size_in_bytes') or 0)})"
