import json

from unsafie.settings import settings

NAME = "unsafie"

# Writing is the token's job. The App only gets what a personal access token cannot do:
# the Checks API, and the reads GitHub requires before it will deliver the events below.
PERMISSIONS = {
    "metadata": "read",
    "contents": "read",
    "issues": "read",
    "pull_requests": "read",
    "actions": "read",
    "deployments": "read",
    "members": "read",
    "checks": "write",
}

EVENTS = [
    "push",
    "pull_request",
    "pull_request_review",
    "pull_request_review_comment",
    "issues",
    "issue_comment",
    "release",
    "create",
    "delete",
    "workflow_run",
    "workflow_job",
    "check_run",
    "check_suite",
    "deployment_status",
    "star",
    "fork",
    "member",
    "repository",
    "public",
]


def webhook_url() -> str:
    return f"{settings.github_origin}/gh/webhook"


def redirect_url() -> str:
    return f"{settings.github_origin}/gh/app/created"


def build(name: str = NAME) -> dict:
    return {
        "name": name,
        "url": settings.public_origin,
        "hook_attributes": {"url": webhook_url(), "active": True},
        "redirect_url": redirect_url(),
        "setup_on_update": True,
        "public": False,
        "default_events": EVENTS,
        "default_permissions": PERMISSIONS,
    }


def as_json(name: str = NAME) -> str:
    return json.dumps(build(name), ensure_ascii=False)


def create_url(organization: str | None = None) -> str:
    if organization:
        return f"https://github.com/organizations/{organization}/settings/apps/new"
    return "https://github.com/settings/apps/new"


def install_url(slug: str) -> str:
    return f"https://github.com/apps/{slug}/installations/new"


def manage_url(installation_id: int) -> str:
    return f"https://github.com/settings/installations/{installation_id}"
