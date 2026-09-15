import asyncio
import contextlib
import json
import os
import pty
import select
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from unsafie import cluster
from unsafie.database import SessionLocal
from unsafie.database.repositories.ci import CiRepository
from unsafie.github.app import auth
from unsafie.github.ci import checks, monitor
from unsafie.log import get_logger

logger = get_logger(__name__)

BASE_DIR = Path("/var/lib/unsafie/ci")
CACHE_DIR = BASE_DIR / "cache"
WORKSPACES_DIR = BASE_DIR / "workspaces"
LOGS_DIR = BASE_DIR / "logs"

for d in (CACHE_DIR, WORKSPACES_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)


async def _sync_repo(installation_id: int, repo_full_name: str) -> Path:
    token = await auth.installation_token(installation_id)
    repo_cache = CACHE_DIR / f"{repo_full_name}.git"
    repo_cache.parent.mkdir(parents=True, exist_ok=True)
    clone_url = f"https://x-access-token:{token}@github.com/{repo_full_name}.git"
    if not (repo_cache / "HEAD").exists():
        proc = await asyncio.create_subprocess_exec(
            "git",
            "clone",
            "--mirror",
            clone_url,
            str(repo_cache),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            msg = f"git mirror failed: {err.decode('utf-8', 'ignore')}"
            raise RuntimeError(msg)
    else:
        await asyncio.create_subprocess_exec(
            "git",
            f"--git-dir={repo_cache}",
            "remote",
            "set-url",
            "origin",
            clone_url,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc = await asyncio.create_subprocess_exec(
            "git",
            f"--git-dir={repo_cache}",
            "fetch",
            "--prune",
            "origin",
            "+refs/heads/*:refs/heads/*",
            "+refs/pull/*:refs/pull/*",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            msg = f"git fetch failed: {err.decode('utf-8', 'ignore')}"
            raise RuntimeError(msg)
    return repo_cache


async def _create_worktree(repo_cache: Path, run_id: int, commit_sha: str) -> Path:
    ws = WORKSPACES_DIR / str(run_id)
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    proc = await asyncio.create_subprocess_exec(
        "git",
        f"--git-dir={repo_cache}",
        "worktree",
        "add",
        "--detach",
        str(ws),
        commit_sha,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        msg = f"git worktree add failed: {err.decode('utf-8', 'ignore')}"
        raise RuntimeError(msg)
    return ws


async def _remove_worktree(repo_cache: Path, run_id: int) -> None:
    ws = WORKSPACES_DIR / str(run_id)
    if not ws.exists():
        return
    proc = await asyncio.create_subprocess_exec(
        "git",
        f"--git-dir={repo_cache}",
        "worktree",
        "remove",
        "--force",
        str(ws),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await proc.wait()
    shutil.rmtree(ws, ignore_errors=True)


async def discover_targets(ws: Path) -> tuple[str, list[str], list[str]]:
    has_just = (ws / "justfile").is_file() or (ws / "Justfile").is_file()
    if has_just and shutil.which("just"):
        proc = await asyncio.create_subprocess_exec(
            "just",
            "--summary",
            cwd=str(ws),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        recipes = out.decode("utf-8", "ignore").split()
        ci_targets = sorted([r for r in recipes if r.startswith("ci-")])
        cd_targets = sorted([r for r in recipes if r.startswith("cd-")])
        return "just", ci_targets, cd_targets

    has_make = (ws / "Makefile").is_file() or (ws / "makefile").is_file()
    if has_make and shutil.which("make"):
        ci_targets = []
        cd_targets = []
        make_file = ws / "Makefile" if (ws / "Makefile").is_file() else ws / "makefile"
        try:
            content = make_file.read_text(encoding="utf-8", errors="ignore")
            for line in content.splitlines():
                target = line.partition(":")[0].strip()
                if target.startswith("ci-") and target not in ci_targets:
                    ci_targets.append(target)
                elif target.startswith("cd-") and target not in cd_targets:
                    cd_targets.append(target)
        except Exception:
            pass
        return "make", sorted(ci_targets), sorted(cd_targets)

    return "none", [], []


async def _run_command_pty(
    run_id: int,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_file_path: Path,
    job_name: str | None = None,
) -> int:
    loop = asyncio.get_running_loop()
    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(cwd),
        env=env,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    os.close(slave_fd)

    pgid = proc.pid
    prev_time = time.time()
    prev_rss, prev_ticks = monitor.get_pgrp_stats(pgid)
    prev_rx, prev_tx = monitor.get_net_bytes()
    clk_tck = os.sysconf("SC_CLK_TCK") or 100

    async def _sample():
        nonlocal prev_time, prev_rss, prev_ticks, prev_rx, prev_tx
        cur_time = time.time()
        dt = max(cur_time - prev_time, 0.05)
        rss_mb, cur_ticks = monitor.get_pgrp_stats(pgid)
        cur_rx, cur_tx = monitor.get_net_bytes()

        cpu_pct = round(max((cur_ticks - prev_ticks) / clk_tck / dt * 100, 0), 1)
        rx_kbps = round(max(cur_rx - prev_rx, 0) / 1024 / dt, 1)
        tx_kbps = round(max(cur_tx - prev_tx, 0) / 1024 / dt, 1)

        prev_time = cur_time
        prev_ticks = cur_ticks
        prev_rx = cur_rx
        prev_tx = cur_tx

        async with SessionLocal() as session:
            await CiRepository(session).record_metrics(
                run_id, cpu_pct, rss_mb, rx_kbps, tx_kbps, job_name=job_name
            )

        metric_payload = json.dumps(
            {
                "type": "metric",
                "job": job_name,
                "cpu": cpu_pct,
                "rss": rss_mb,
                "rx": rx_kbps,
                "tx": tx_kbps,
                "time": datetime.now(UTC).isoformat(),
            }
        )
        with contextlib.suppress(Exception):
            await cluster.client().publish(f"ci:run:{run_id}:stream", metric_payload)
            if job_name:
                await cluster.client().publish(f"ci:run:{run_id}:{job_name}:stream", metric_payload)

    async def _heartbeat_and_monitor():
        hb_counter = 0
        while proc.poll() is None:
            await asyncio.sleep(0.5)
            await _sample()
            hb_counter += 1
            if hb_counter % 10 == 0:
                async with SessionLocal() as session:
                    await CiRepository(session).renew_lease(run_id, 30)

    monitor_task = asyncio.create_task(_heartbeat_and_monitor())

    async def _publish(channel: str, message: str) -> None:
        await cluster.client().publish(channel, message)

    def _read_output():
        with open(log_file_path, "ab") as lf:
            while True:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if r:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            break
                        lf.write(data)
                        lf.flush()
                        chunk_str = data.decode("utf-8", "replace")
                        asyncio.run_coroutine_threadsafe(
                            _publish(
                                f"ci:run:{run_id}:stream",
                                json.dumps({"type": "log", "chunk": chunk_str, "job": job_name}),
                            ),
                            loop,
                        )
                        if job_name:
                            asyncio.run_coroutine_threadsafe(
                                _publish(
                                    f"ci:run:{run_id}:{job_name}:stream",
                                    json.dumps(
                                        {"type": "log", "chunk": chunk_str, "job": job_name}
                                    ),
                                ),
                                loop,
                            )
                    except OSError:
                        break
                elif proc.poll() is not None:
                    break

    await loop.run_in_executor(None, _read_output)
    proc.wait()
    monitor_task.cancel()
    with contextlib.suppress(Exception):
        await _sample()
    os.close(master_fd)
    return proc.returncode


async def execute_run(run_id: int) -> None:
    async with SessionLocal() as session:
        ci_repo = CiRepository(session)
        run = await ci_repo.get_run(run_id)
        if not run:
            return

    main_log_path = LOGS_DIR / f"{run_id}.log"
    with open(main_log_path, "w", encoding="utf-8") as f:
        f.write(
            f"=== unsafie ci runner starting for {run.repo_full_name} @ {run.commit_sha[:8]} ===\n"
        )

    repo_cache = None
    try:
        repo_cache = await _sync_repo(run.installation_id, run.repo_full_name)
        ws = await _create_worktree(repo_cache, run.id, run.commit_sha)
    except Exception as e:
        logger.exception("ci preparation failed for run %s", run.id)
        with open(main_log_path, "a", encoding="utf-8") as f:
            f.write(f"\nError during checkout: {e}\n")
        async with SessionLocal() as session:
            await CiRepository(session).finish_run(
                run.id,
                status="failure",
                exit_code=1,
                error_message=str(e),
                log_path=str(main_log_path),
            )
        return

    try:
        tool, ci_targets, cd_targets = await discover_targets(ws)
        if not ci_targets and not cd_targets:
            with open(main_log_path, "a", encoding="utf-8") as f:
                f.write("\nNo 'ci-*' or 'cd-*' targets found in justfile or Makefile. Skipping.\n")
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(
                    run.id,
                    status="success",
                    exit_code=0,
                    log_path=str(main_log_path),
                )
            check_run_id = await checks.create_check_run(
                run.installation_id,
                run.repo_full_name,
                run.commit_sha,
                run.id,
                name="ci / check",
                slug=run.slug,
            )
            if check_run_id:
                await checks.update_check_run(
                    run.installation_id,
                    run.repo_full_name,
                    check_run_id,
                    status="completed",
                    conclusion="neutral",
                    title="No Targets Found",
                    summary="Neither `justfile` nor `Makefile` had `ci-*` or `cd-*` targets.",
                )
            return

        base_env = os.environ.copy()
        base_env["CI"] = "true"
        base_env["UNSAFIE_CI"] = "true"
        base_env["GITHUB_SHA"] = run.commit_sha
        base_env["GITHUB_REF"] = run.ref
        base_env["GITHUB_BRANCH"] = run.branch
        base_env["GITHUB_REPOSITORY"] = run.repo_full_name

        async def _run_job(target: str, stage: str, env: dict[str, str]) -> int:
            async with SessionLocal() as session:
                job_row = await CiRepository(session).create_job(run.id, target, stage)

            display_name = f"{stage} / {target.removeprefix(f'{stage}-')}"
            check_run_id = await checks.create_check_run(
                run.installation_id,
                run.repo_full_name,
                run.commit_sha,
                run.id,
                name=display_name,
                job_name=target,
                slug=run.slug,
            )
            if check_run_id:
                async with SessionLocal() as session:
                    await CiRepository(session).set_job_check_run_id(job_row.id, check_run_id)

            async with SessionLocal() as session:
                await CiRepository(session).start_job(job_row.id)

            job_log_path = LOGS_DIR / f"{run.id}_{target}.log"
            with open(job_log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Running {tool} {target} ===\n")

            cmd = [tool, target]
            exit_code = await _run_command_pty(run.id, cmd, ws, env, job_log_path, job_name=target)

            tail_log = ""
            try:
                with open(job_log_path, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    tail_log = "".join(lines[-40:])
            except Exception:
                pass

            if exit_code == 0:
                async with SessionLocal() as session:
                    await CiRepository(session).finish_job(
                        job_row.id,
                        status="success",
                        exit_code=0,
                        log_path=str(job_log_path),
                    )
                if check_run_id:
                    await checks.update_check_run(
                        run.installation_id,
                        run.repo_full_name,
                        check_run_id,
                        status="completed",
                        conclusion="success",
                        title=f"{target} Succeeded",
                        summary=f"`{tool} {target}` passed successfully.",
                        text=f"```\n{tail_log}\n```",
                    )
            else:
                async with SessionLocal() as session:
                    await CiRepository(session).finish_job(
                        job_row.id,
                        status="failure",
                        exit_code=exit_code,
                        error_message=f"`{tool} {target}` exited with code {exit_code}",
                        log_path=str(job_log_path),
                    )
                if check_run_id:
                    await checks.update_check_run(
                        run.installation_id,
                        run.repo_full_name,
                        check_run_id,
                        status="completed",
                        conclusion="failure",
                        title=f"{target} Failed",
                        summary=f"`{tool} {target}` failed with exit code {exit_code}.",
                        text=f"```\n{tail_log}\n```",
                    )
            return exit_code

        ci_codes = []
        if ci_targets:
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(
                    run.id, status="in_progress", current_stage="ci"
                )
            ci_codes = await asyncio.gather(*[_run_job(t, "ci", base_env) for t in ci_targets])

        all_ci_ok = all(c == 0 for c in ci_codes) if ci_codes else True

        cd_codes = []
        if all_ci_ok and run.is_default_branch and cd_targets:
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(
                    run.id, status="in_progress", current_stage="cd"
                )
                secrets = await CiRepository(session).get_secrets(run.repo_full_name)

            cd_env = base_env.copy()
            cd_env.update(secrets)
            cd_codes = await asyncio.gather(*[_run_job(t, "cd", cd_env) for t in cd_targets])

        all_cd_ok = all(c == 0 for c in cd_codes) if cd_codes else True
        final_ok = all_ci_ok and all_cd_ok

        with open(main_log_path, "a", encoding="utf-8") as f:
            for t in ci_targets + cd_targets:
                job_log = LOGS_DIR / f"{run.id}_{t}.log"
                if job_log.is_file():
                    f.write(f"\n--- [Job: {t}] ---\n")
                    f.write(job_log.read_text(encoding="utf-8", errors="replace"))

        async with SessionLocal() as session:
            await CiRepository(session).finish_run(
                run.id,
                status="success" if final_ok else "failure",
                exit_code=0 if final_ok else 1,
                log_path=str(main_log_path),
            )

    finally:
        if repo_cache:
            await _remove_worktree(repo_cache, run.id)
