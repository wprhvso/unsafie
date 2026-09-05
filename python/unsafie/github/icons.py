CONCLUSION = {
    "success": "✅",
    "failure": "❌",
    "cancelled": "⛔",
    "timed_out": "⏱",
    "skipped": "⏭",
    "neutral": "➖",
    "action_required": "⚠️",
    "stale": "🕸",
    "startup_failure": "💥",
}

STATE = {"open": "🟢", "closed": "🔴", "merged": "🟣", "draft": "📝"}

EVENT = {
    "push": "⬆️",
    "pull_request": "🔀",
    "issues": "📌",
    "issue_comment": "💬",
    "pull_request_review": "🔍",
    "pull_request_review_comment": "💬",
    "release": "🏷",
    "create": "🌱",
    "delete": "🗑",
    "workflow_run": "⚙️",
    "check_run": "🔬",
    "deployment_status": "🚀",
    "star": "⭐",
    "fork": "🍴",
    "member": "👥",
    "repository": "📦",
    "public": "🌍",
    "mention": "📣",
}


def conclusion(value: str | None) -> str:
    return CONCLUSION.get(value or "", "❔")


def pull_state(pull: dict) -> str:
    if pull.get("merged"):
        return STATE["merged"]
    if pull.get("draft"):
        return STATE["draft"]
    return STATE.get(pull.get("state") or "open", "🟢")
