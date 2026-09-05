from unsafie.github import icons
from unsafie.mime import human_size


def issue_line(item: dict) -> str:
    state = icons.STATE.get(item.get("state") or "open", "•")
    labels = ",".join(label["name"] for label in item.get("labels") or [])
    tail = f" [{labels}]" if labels else ""
    who = (item.get("user") or {}).get("login") or "?"
    return f"{state} #{item.get('number')} {item.get('title')} — {who}{tail}"


def pull_line(item: dict) -> str:
    head = (item.get("head") or {}).get("ref") or "?"
    base = (item.get("base") or {}).get("ref") or "?"
    draft = " (draft)" if item.get("draft") else ""
    return f"{icons.pull_state(item)} #{item.get('number')} {item.get('title')}{draft} — {head} → {base}"


def run_line(item: dict) -> str:
    status = item.get("status")
    mark = icons.conclusion(item.get("conclusion")) if status == "completed" else "🔄"
    return (
        f"{mark} #{item.get('run_number')} {item.get('name')} · {item.get('head_branch')} · "
        f"{item.get('conclusion') or status} · id={item.get('id')}"
    )


def job_line(item: dict) -> str:
    mark = icons.conclusion(item.get("conclusion")) if item.get("status") == "completed" else "🔄"
    return f"{mark} {item.get('name')} · {item.get('conclusion') or item.get('status')} · id={item.get('id')}"


def commit_line(item: dict) -> str:
    message = (item.get("commit") or {}).get("message") or ""
    author = ((item.get("commit") or {}).get("author") or {}).get("name") or "?"
    return (
        f"`{(item.get('sha') or '')[:7]}` {message.splitlines()[0] if message else ''} — {author}"
    )


def release_line(item: dict) -> str:
    flags = " (draft)" if item.get("draft") else (" (pre)" if item.get("prerelease") else "")
    return f"🏷 {item.get('tag_name')}{flags} {item.get('name') or ''}"


def comment_block(item: dict) -> str:
    who = (item.get("user") or {}).get("login") or "?"
    when = (item.get("created_at") or "")[:16].replace("T", " ")
    return f"— {who} ({when}, id={item.get('id')})\n{item.get('body') or ''}"


def artifact_line(item: dict) -> str:
    expired = " (expired)" if item.get("expired") else ""
    return f"{item.get('name')} · {human_size(item.get('size_in_bytes') or 0)} · id={item.get('id')}{expired}"


def tree_listing(dirs: list[str], files: list[str]) -> str:
    return "\n".join([*(f"{d}" for d in dirs), *files]) or "<empty>"
