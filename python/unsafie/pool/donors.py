import base64
import hashlib
from unsafie.log import get_logger
import secrets
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from unsafie.database import SessionLocal
from unsafie.database.models.pool import PoolDonor
from unsafie.errors import OpsError
from unsafie.github.client.base import GithubHTTP
from unsafie.github.errors import GithubError, NotFound
from unsafie.github.sealed_box import seal
from unsafie.settings import settings

logger = get_logger(__name__)

WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "machine.yml"
SECRET_URL = "UNSAFIE_URL"
SECRET_TOKEN = "UNSAFIE_WORKER_TOKEN"
SECRET_SPEC = "UNSAFIE_SDK_SPEC"
SECRET_WIRE = "UNSAFIE_WIRE_SPEC"
SECRET_CACHE = "UNSAFIE_CACHE_URL"


class DonorError(OpsError):
    pass


def digest(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


async def all_donors(enabled_only: bool = False) -> list[PoolDonor]:
    async with SessionLocal() as session:
        query = select(PoolDonor).order_by(PoolDonor.id)
        if enabled_only:
            query = query.where(PoolDonor.enabled.is_(True))
        rows = await session.scalars(query)
        return list(rows)


async def by_login(login: str) -> PoolDonor | None:
    async with SessionLocal() as session:
        return await session.scalar(select(PoolDonor).where(PoolDonor.login == login))


async def by_worker_token(raw: str) -> PoolDonor | None:
    async with SessionLocal() as session:
        return await session.scalar(
            select(PoolDonor).where(PoolDonor.worker_token_hash == digest(raw)),
        )


async def add(token: str, jobs: int = 20, label: str | None = None) -> tuple[PoolDonor, str]:
    http = GithubHTTP(token)
    try:
        me = await http.request("GET", "/user")
    except GithubError as refused:
        msg = f"github rejected this token: {refused}"
        raise DonorError(msg) from None
    login = str(me.get("login") or "")
    if not login:
        msg = "the token does not resolve to an account"
        raise DonorError(msg)
    worker_token = secrets.token_urlsafe(32)
    async with SessionLocal() as session:
        donor = await session.scalar(select(PoolDonor).where(PoolDonor.login == login))
        if donor is None:
            donor = PoolDonor(login=login, repo=f"{login}/{settings.pool_repo_name}")
            session.add(donor)
        donor.token = token
        donor.label = label
        donor.jobs = jobs
        donor.workflow = settings.pool_workflow
        donor.worker_token_hash = digest(worker_token)
        donor.enabled = True
        donor.state = "new"
        donor.last_error = None
        await session.commit()
        await session.refresh(donor)
    logger.info("pool donor %s added (%s jobs)", login, jobs)
    return donor, worker_token


async def rotate(login: str) -> str:
    worker_token = secrets.token_urlsafe(32)
    async with SessionLocal() as session:
        donor = await session.scalar(select(PoolDonor).where(PoolDonor.login == login))
        if donor is None:
            msg = f"no donor '{login}'"
            raise DonorError(msg)
        donor.worker_token_hash = digest(worker_token)
        await session.commit()
    return worker_token


async def remove(login: str) -> bool:
    async with SessionLocal() as session:
        donor = await session.scalar(select(PoolDonor).where(PoolDonor.login == login))
        if donor is None:
            return False
        await session.delete(donor)
        await session.commit()
    return True


async def enable(login: str, on: bool) -> bool:
    async with SessionLocal() as session:
        donor = await session.scalar(select(PoolDonor).where(PoolDonor.login == login))
        if donor is None:
            return False
        donor.enabled = on
        await session.commit()
    return True


async def note(donor_id: int, state: str, error: str | None = None) -> None:
    async with SessionLocal() as session:
        donor = await session.get(PoolDonor, donor_id)
        if donor is None:
            return
        donor.state = state
        donor.last_error = error
        donor.reconciled_at = datetime.now(UTC)
        await session.commit()


async def bootstrap(login: str, worker_token: str | None = None) -> dict:
    donor = await by_login(login)
    if donor is None:
        msg = f"no donor '{login}'"
        raise DonorError(msg)
    if worker_token is None:
        worker_token = await rotate(login)
    http = GithubHTTP(donor.token)
    owner, _, name = donor.repo.partition("/")
    try:
        repo = await http.request("GET", f"/repos/{owner}/{name}")
    except NotFound:
        repo = await http.request(
            "POST",
            "/user/repos" if owner == login else f"/orgs/{owner}/repos",
            json_body={"name": name, "private": False, "auto_init": True},
        )
        logger.info("pool donor %s: repository %s created", login, donor.repo)
    branch = repo.get("default_branch") or "main"
    await _put_workflow(http, donor.repo, branch, donor.workflow)
    secrets_to_seal = {
        SECRET_URL: settings.public_origin,
        SECRET_TOKEN: worker_token,
        SECRET_SPEC: settings.pool_sdk_spec,
        SECRET_WIRE: settings.pool_wire_spec,
    }
    if settings.pool_cache_url:
        secrets_to_seal[SECRET_CACHE] = settings.pool_cache_url.rstrip("/")
    await _put_secrets(http, donor.repo, secrets_to_seal)
    await note(donor.id, "ready")
    return {"repo": donor.repo, "branch": branch, "workflow": donor.workflow}


async def _put_workflow(http: GithubHTTP, repo: str, branch: str, workflow: str) -> None:
    if not WORKFLOW.is_file():
        msg = f"the machine workflow is missing at {WORKFLOW}"
        raise DonorError(msg)
    content = base64.b64encode(WORKFLOW.read_bytes()).decode()
    path = f"/repos/{repo}/contents/.github/workflows/{workflow}"
    body: dict = {"message": "unsafie: machine workflow", "content": content, "branch": branch}
    try:
        existing = await http.request("GET", path, params={"ref": branch})
    except NotFound:
        existing = None
    if existing is not None:
        if str(existing.get("content", "")).replace("\n", "") == content:
            return
        body["sha"] = existing["sha"]
    await http.request("PUT", path, json_body=body)
    logger.info("pool donor repo %s: workflow %s written", repo, workflow)


async def _put_secrets(http: GithubHTTP, repo: str, values: dict[str, str]) -> None:
    key = await http.request("GET", f"/repos/{repo}/actions/secrets/public-key")
    for name, value in values.items():
        await http.request(
            "PUT",
            f"/repos/{repo}/actions/secrets/{name}",
            json_body={"encrypted_value": seal(key["key"], value), "key_id": key["key_id"]},
        )
    logger.info("pool donor repo %s: secrets set (%s)", repo, ", ".join(values))
