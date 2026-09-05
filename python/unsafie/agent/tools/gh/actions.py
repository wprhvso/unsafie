import io
import logging
import zipfile

from unsafie.agent.tools.base import ToolContext, guarded, schema, text
from unsafie.agent.tools.files import deliver
from unsafie.agent.tools.gh.context import SERVER, session_for
from unsafie.agent.tools.gh.format import artifact_line, job_line, run_line
from unsafie.agent.tools.registry import register
from unsafie.github.errors import GithubError, NotFound
from unsafie.mime import human_size

logger = logging.getLogger(__name__)

REPO_ARGS = dict(repo=str)
LOG_TAIL = 20_000


@register(
    SERVER,
    "actions_runs",
    "Workflow runs: workflow — file name or id, branch, status (queued|in_progress|completed|failure), "
    "limit. Without arguments — the latest runs of the repository.",
    schema([], workflow=str, branch=str, status=str, limit=int, **REPO_ARGS),
)
@guarded
async def actions_runs(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    items = await state.client.runs(
        args.get("workflow"),
        args.get("branch"),
        args.get("status"),
        max(1, min(int(args.get("limit") or 15), 50)),
    )
    if not items:
        return text(f"no runs in {state.repo.full}")
    return text(f"{state.repo.full}:\n" + "\n".join(run_line(r) for r in items))


@register(
    SERVER,
    "actions_jobs",
    "Jobs of one run: run_id (from actions_runs). Shows which step failed.",
    schema(["run_id"], run_id=int, **REPO_ARGS),
)
@guarded
async def actions_jobs(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    run_id = int(args["run_id"])
    run = await state.client.run(run_id)
    jobs = await state.client.jobs(run_id)
    lines = [run_line(run), ""]
    for job in jobs:
        lines.append(job_line(job))
        for step in job.get("steps") or []:
            if step.get("conclusion") not in ("success", "skipped", None):
                lines.append(f"    ↳ step '{step.get('name')}': {step.get('conclusion')}")
    return text("\n".join(lines))


@register(
    SERVER,
    "actions_logs",
    "Logs of a job: job_id (from actions_jobs). Returns the tail of the log — usually enough to see "
    "the error. full=true sends the whole log to the chat as a file.",
    schema(["job_id"], job_id=int, full=bool, **REPO_ARGS),
)
@guarded
async def actions_logs(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    job_id = int(args["job_id"])
    data = await state.client.job_logs(job_id)
    if not data:
        raise NotFound(f"no logs for job {job_id} (may have expired)")
    if args.get("full"):
        return await deliver(ctx, data, f"job-{job_id}.log", caption=f"log of job {job_id}")
    body = data.decode(errors="replace")
    tail = body[-LOG_TAIL:]
    head = f"job {job_id}, {human_size(len(data))}"
    if len(body) > LOG_TAIL:
        head += f" (last {LOG_TAIL} chars; full=true sends the whole file)"
    return text(f"{head}\n\n{tail}")


@register(
    SERVER,
    "actions_run",
    "Start a workflow manually (workflow_dispatch): workflow — file name (ci.yml) or id, ref — branch, "
    "inputs — a JSON object of parameters.",
    schema(["workflow"], workflow=str, ref=str, inputs=str, **REPO_ARGS),
)
@guarded
async def actions_run(ctx: ToolContext, args: dict) -> dict:
    import json

    state = await session_for(ctx, args)
    inputs = None
    if raw := args.get("inputs"):
        try:
            inputs = json.loads(raw)
        except ValueError as e:
            raise GithubError(f"inputs is not JSON: {e}") from None
    ref = args.get("ref") or state.branch
    await state.client.dispatch(args["workflow"], ref, inputs)
    return text(f"workflow {args['workflow']} started on `{ref}` in {state.repo.full}")


@register(
    SERVER,
    "actions_control",
    "Control a run: run_id + rerun=true (failed_only=true — only failed jobs) or cancel=true.",
    schema(["run_id"], run_id=int, rerun=bool, failed_only=bool, cancel=bool, **REPO_ARGS),
)
@guarded
async def actions_control(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    run_id = int(args["run_id"])
    if args.get("cancel"):
        await state.client.cancel(run_id)
        return text(f"run {run_id} cancelled")
    if args.get("rerun"):
        await state.client.rerun(run_id, bool(args.get("failed_only")))
        return text(
            f"run {run_id} restarted" + (" (failed jobs only)" if args.get("failed_only") else "")
        )
    raise GithubError("rerun=true or cancel=true is required")


@register(
    SERVER,
    "actions_workflows",
    "Workflows of the repository: name, file, state.",
    schema([], **REPO_ARGS),
)
@guarded
async def actions_workflows(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    items = await state.client.workflows()
    if not items:
        return text(f"no workflows in {state.repo.full}")
    lines = [
        f"{w['name']} · {w['path'].rsplit('/', 1)[-1]} · {w['state']} · id={w['id']}" for w in items
    ]
    return text(f"{state.repo.full}:\n" + "\n".join(lines))


@register(
    SERVER,
    "actions_artifacts",
    "Artifacts of a run: run_id — the list; artifact_id — download and send the file to the chat "
    "(a single file inside a zip is unpacked, otherwise the zip is sent). name — a file inside the archive.",
    schema([], run_id=int, artifact_id=int, name=str, **REPO_ARGS),
)
@guarded
async def actions_artifacts(ctx: ToolContext, args: dict) -> dict:
    state = await session_for(ctx, args)
    if artifact_id := args.get("artifact_id"):
        data = await state.client.artifact_zip(int(artifact_id))
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            names = [n for n in archive.namelist() if not n.endswith("/")]
        except zipfile.BadZipFile:
            return await deliver(ctx, data, f"artifact-{artifact_id}.zip")
        wanted = args.get("name") or (names[0] if len(names) == 1 else None)
        if wanted is None:
            listing = "\n".join(names[:50])
            return text(f"the artifact contains {len(names)} file(s); pass name=:\n{listing}")
        if wanted not in names:
            raise NotFound(f"{wanted} is not in the artifact")
        return await deliver(ctx, archive.read(wanted), wanted.rsplit("/", 1)[-1])
    if not args.get("run_id"):
        raise GithubError("run_id or artifact_id is required")
    items = await state.client.artifacts(int(args["run_id"]))
    if not items:
        return text("no artifacts for this run")
    return text("\n".join(artifact_line(a) for a in items))
