from dataclasses import dataclass

from unsafie.fluent import t

KINDS: dict[str, tuple[str, ...]] = {
    "ci": ("workflow_run", "check_suite"),
    "push": ("push",),
    "pr": ("pull_request",),
    "pr_comments": ("pull_request_review", "pull_request_review_comment"),
    "issues": ("issues",),
    "issue_comments": ("issue_comment",),
    "releases": ("release", "create"),
    "deploys": ("deployment_status",),
    "stars": ("star", "fork"),
    "admin": ("member", "repository", "public", "delete"),
    "mentions": (),
    "all": (),
}

FILTERS = ("branch", "author", "label", "workflow", "ignore_self", "only_failures")


@dataclass(frozen=True)
class Match:
    kind: str
    reason: str = ""


def kinds_for_event(event: str) -> list[str]:
    return [kind for kind, events in KINDS.items() if event in events]


def valid_kind(kind: str) -> bool:
    return kind in KINDS


def describe(sub, repo, locale: str | None = None) -> str:
    bits = []
    for key in FILTERS:
        value = (sub.filters or {}).get(key)
        if value in (None, "", False):
            continue
        bits.append(key if value is True else f"{key}={value}")
    suffix = f" [{', '.join(bits)}]" if bits else ""
    return f"[{sub.id}] {repo.owner}/{repo.name} · {sub.kind}{suffix}"


def summary(subs: list[tuple], locale: str | None = None) -> str:
    if not subs:
        return t("github-subs-empty", locale)
    return "\n".join(describe(s, r, locale) for s, r in subs)


def matches(sub, event: str, payload: dict, logins: set[str]) -> bool:
    filters = sub.filters or {}
    if sub.kind == "mentions":
        return False
    if sub.kind != "all" and event not in KINDS.get(sub.kind, ()):
        return False
    sender = ((payload.get("sender") or {}).get("login") or "").lower()
    if filters.get("ignore_self") and sender and sender in logins:
        return False
    if branch := filters.get("branch"):
        if _branch_of(event, payload) not in (None, branch):
            return False
    if author := filters.get("author"):
        if _author_of(payload).lower() != str(author).lower():
            return False
    if label := filters.get("label"):
        labels = {
            (item.get("name") or "").lower()
            for item in (
                (payload.get("issue") or payload.get("pull_request") or {}).get("labels") or []
            )
        }
        if str(label).lower() not in labels:
            return False
    if workflow := filters.get("workflow"):
        name = (payload.get("workflow_run") or {}).get("name") or ""
        if name and str(workflow).lower() not in name.lower():
            return False
    if filters.get("only_failures"):
        run = payload.get("workflow_run") or payload.get("check_suite") or {}
        if (run.get("conclusion") or "success") == "success":
            return False
    return True


def _branch_of(event: str, payload: dict) -> str | None:
    if event == "push":
        return (payload.get("ref") or "").removeprefix("refs/heads/") or None
    if run := payload.get("workflow_run"):
        return run.get("head_branch")
    if suite := payload.get("check_suite"):
        return suite.get("head_branch")
    if pull := payload.get("pull_request"):
        return (pull.get("base") or {}).get("ref")
    return None


def _author_of(payload: dict) -> str:
    for key in ("comment", "issue", "pull_request", "release", "review"):
        item = payload.get(key)
        if isinstance(item, dict) and item.get("user"):
            return item["user"].get("login") or ""
    return (payload.get("sender") or {}).get("login") or ""


def mentioned(payload: dict, logins: set[str]) -> str | None:
    texts = []
    for key in ("comment", "issue", "pull_request", "review", "release"):
        item = payload.get(key)
        if isinstance(item, dict):
            texts.append(item.get("body") or "")
            texts.append(item.get("title") or "")
    haystack = "\n".join(texts).lower()
    for login in logins:
        if f"@{login}" in haystack:
            return login
    return None
