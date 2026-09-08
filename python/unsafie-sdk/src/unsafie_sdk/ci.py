from unsafie_sdk.client import client


def add(repo: str, *, label: str = "pool", jobs: int | None = None, idle: int | None = None,
        lifetime: int | None = None) -> dict:
    """Run the CI of a repository on the pool. Needs a token with Administration: read and write."""
    body = {"repo": repo, "label": label, "jobs": jobs, "idle": idle, "lifetime": lifetime}
    answer = client().call("POST", "/ci", body)
    return {**answer["repo"], "snippet": answer["snippet"]}


def listing() -> list[dict]:
    """Repositories wired to the pool."""
    return client().call("GET", "/ci").get("repos", [])


def status(repo: str) -> dict:
    """Live runners, recent jobs and the state of the controller for a repository."""
    return client().call("GET", f"/ci/{repo}")


def jobs(repo: str, limit: int = 50) -> list[dict]:
    """What the runners of this repository did."""
    return client().call("GET", f"/ci/{repo}/jobs", params={"limit": limit}).get("jobs", [])


def snippet(repo: str) -> str:
    """The runs-on block to paste into the workflow."""
    return str(client().call("GET", f"/ci/{repo}/snippet")["snippet"])


def remove(repo: str) -> dict:
    """Stop running this repository on the pool."""
    return client().call("DELETE", f"/ci/{repo}")
