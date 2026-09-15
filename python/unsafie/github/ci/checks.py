from datetime import UTC, datetime
from typing import Any

from unsafie.github.app import auth
from unsafie.github.client.base import session as http_session
from unsafie.log import get_logger
from unsafie.settings import settings

logger = get_logger(__name__)


async def _headers(installation_id: int) -> dict[str, str]:
    token = await auth.installation_token(installation_id)
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "unsafie-ci",
    }


async def create_check_run(
    installation_id: int,
    repo_full_name: str,
    commit_sha: str,
    run_id: int,
    name: str = "ci",
    job_name: str | None = None,
    slug: str | None = None,
) -> int | None:
    headers = await _headers(installation_id)
    now = datetime.now(UTC).isoformat()
    base = (
        f"{settings.public_origin}/{slug}" if slug else f"{settings.public_origin}/ci/runs/{run_id}"
    )
    details_url = f"{base}?job={job_name}" if job_name else base
    payload = {
        "name": name,
        "head_sha": commit_sha,
        "status": "in_progress",
        "started_at": now,
        "details_url": details_url,
    }
    http = await http_session()
    url = f"{settings.github_api_url}/repos/{repo_full_name}/check-runs"
    async with http.post(url, json=payload, headers=headers) as resp:
        if resp.status in (200, 201):
            data = await resp.json(content_type=None)
            return data.get("id")
        text = await resp.text()
        logger.error("failed to create check run: %s %s", resp.status, text)
        return None


async def update_check_run(
    installation_id: int,
    repo_full_name: str,
    check_run_id: int,
    *,
    status: str = "completed",
    conclusion: str | None = None,
    title: str = "CI",
    summary: str = "",
    text: str | None = None,
) -> bool:
    headers = await _headers(installation_id)
    output: dict[str, str] = {
        "title": title[:255],
        "summary": summary[:65535],
    }
    if text:
        output["text"] = text[:65535]
    payload: dict[str, Any] = {
        "status": status,
        "output": output,
    }
    if conclusion:
        payload["conclusion"] = conclusion
    if status == "completed":
        payload["completed_at"] = datetime.now(UTC).isoformat()
    http = await http_session()
    url = f"{settings.github_api_url}/repos/{repo_full_name}/check-runs/{check_run_id}"
    async with http.patch(url, json=payload, headers=headers) as resp:
        if resp.status in (200, 201):
            return True
        err = await resp.text()
        logger.error("failed to update check run %s: %s %s", check_run_id, resp.status, err)
        return False
