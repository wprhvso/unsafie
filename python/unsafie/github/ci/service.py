import asyncio

from unsafie.database import SessionLocal
from unsafie.database.models.ci import CiRun
from unsafie.database.repositories.ci import CiRepository
from unsafie.log import get_logger

logger = get_logger(__name__)

ci_event = asyncio.Event()


def notify_worker() -> None:
    ci_event.set()


async def enqueue_from_webhook(event: str, payload: dict) -> CiRun | None:
    repo_data = payload.get("repository") or {}
    repo_full_name = repo_data.get("full_name")
    if not repo_full_name:
        return None

    sender_data = payload.get("sender") or {}
    sender = sender_data.get("login")
    owner, _, _ = repo_full_name.partition("/")

    async with SessionLocal() as session:
        ci_repo = CiRepository(session)
        is_sender_ok = await ci_repo.is_whitelisted(sender)
        is_owner_ok = await ci_repo.is_whitelisted(owner)
        if not (is_sender_ok or is_owner_ok):
            logger.warning(
                "sender %s and owner %s are not in ci_whitelist, ignoring ci", sender, owner
            )
            return None

    installation_id = int((payload.get("installation") or {}).get("id") or 0)
    if not installation_id:
        return None

    default_branch = repo_data.get("default_branch") or "main"

    if event == "push":
        if payload.get("deleted"):
            return None
        commit_sha = payload.get("after")
        if not commit_sha or commit_sha.startswith("00000000"):
            return None
        ref = payload.get("ref") or "refs/heads/main"
        branch = ref.removeprefix("refs/heads/")
        is_default_branch = branch == default_branch
        head_commit = payload.get("head_commit") or {}
        commit_message = head_commit.get("message")

        async with SessionLocal() as session:
            run = await CiRepository(session).enqueue_run(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                commit_sha=commit_sha,
                ref=ref,
                branch=branch,
                is_default_branch=is_default_branch,
                sender=sender,
                commit_message=commit_message,
                trigger_event="push",
            )
        notify_worker()
        logger.info("enqueued ci run %s for %s @ %s", run.id, repo_full_name, commit_sha[:7])
        return run

    if event in ("check_run", "check_suite") and payload.get("action") == "rerequested":
        check_run = payload.get("check_run") or {}
        check_suite = payload.get("check_suite") or {}
        commit_sha = check_run.get("head_sha") or check_suite.get("head_sha")
        if not commit_sha:
            return None
        branch = check_run.get("head_branch") or check_suite.get("head_branch") or default_branch
        ref = f"refs/heads/{branch}"
        is_default_branch = branch == default_branch

        async with SessionLocal() as session:
            run = await CiRepository(session).enqueue_run(
                installation_id=installation_id,
                repo_full_name=repo_full_name,
                commit_sha=commit_sha,
                ref=ref,
                branch=branch,
                is_default_branch=is_default_branch,
                sender=sender,
                trigger_event=f"{event}_rerequest",
            )
        notify_worker()
        logger.info("enqueued rerequested ci run %s for %s", run.id, repo_full_name)
        return run

    return None


async def rerequest_run(run_id: int, triggered_by: str | None = None) -> CiRun | None:
    async with SessionLocal() as session:
        ci_repo = CiRepository(session)
        orig = await ci_repo.get_run(run_id)
        if not orig:
            return None
        run = await ci_repo.enqueue_run(
            installation_id=orig.installation_id,
            repo_full_name=orig.repo_full_name,
            commit_sha=orig.commit_sha,
            ref=orig.ref,
            branch=orig.branch,
            is_default_branch=orig.is_default_branch,
            sender=triggered_by or orig.sender,
            commit_message=orig.commit_message,
            trigger_event="manual_rerun",
        )
    notify_worker()
    return run
