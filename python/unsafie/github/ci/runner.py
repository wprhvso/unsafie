import asyncio
import contextlib
import json
import os
import pty
import select
import shutil
import subprocess
import time
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
            "git", "clone", "--mirror", clone_url, str(repo_cache),
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            msg = f"git mirror failed: {err.decode('utf-8', 'ignore')}"
            raise RuntimeError(msg)
    else:
        await asyncio.create_subprocess_exec(
            "git", f"--git-dir={repo_cache}", "remote", "set-url", "origin", clone_url,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        proc = await asyncio.create_subprocess_exec(
            "git", f"--git-dir={repo_cache}", "fetch", "--prune", "origin",
            "+refs/heads/*:refs/heads/*", "+refs/pull/*:refs/pull/*",
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
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
        "git", f"--git-dir={repo_cache}", "worktree", "add", "--detach", str(ws), commit_sha,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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
        "git", f"--git-dir={repo_cache}", "worktree", "remove", "--force", str(ws),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    await proc.wait()
    shutil.rmtree(ws, ignore_errors=True)

async def _discover_targets(ws: Path) -> tuple[str, bool, bool]:
    has_just = (ws / "justfile").is_file() or (ws / "Justfile").is_file()
    if has_just and shutil.which("just"):
        proc = await asyncio.create_subprocess_exec(
            "just", "--summary",
            cwd=str(ws), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        recipes = set(out.decode("utf-8", "ignore").split())
        return "just", ("ci" in recipes), ("cd" in recipes)

    has_make = (ws / "Makefile").is_file() or (ws / "makefile").is_file()
    if has_make and shutil.which("make"):
        proc_ci = await asyncio.create_subprocess_exec(
            "make", "-q", "-n", "ci",
            cwd=str(ws), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ret_ci = await proc_ci.wait()
        proc_cd = await asyncio.create_subprocess_exec(
            "make", "-q", "-n", "cd",
            cwd=str(ws), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ret_cd = await proc_cd.wait()
        return "make", (ret_ci in (0, 1)), (ret_cd in (0, 1))

    return "none", False, False

async def _run_command_pty(
    run_id: int,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    log_file_path: Path,
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

    async def _heartbeat_and_monitor():
        prev_ticks = monitor.get_tree_cpu_ticks(proc.pid)
        prev_time = time.time()
        prev_rx, prev_tx = monitor.get_net_bytes()
        hb_counter = 0
        while proc.poll() is None:
            await asyncio.sleep(1.0)
            hb_counter += 1
            if hb_counter % 5 == 0:
                async with SessionLocal() as session:
                    await CiRepository(session).renew_lease(run_id, 30)

            cur_time = time.time()
            dt = max(cur_time - prev_time, 0.1)
            cur_ticks = monitor.get_tree_cpu_ticks(proc.pid)
            clk_tck = os.sysconf("SC_CLK_TCK") or 100
            cpu_pct = round(((cur_ticks - prev_ticks) / clk_tck / dt) * 100, 1)
            rss_mb = monitor.get_tree_rss_mb(proc.pid)
            cur_rx, cur_tx = monitor.get_net_bytes()
            rx_kbps = round((cur_rx - prev_rx) / 1024 / dt, 1)
            tx_kbps = round((cur_tx - prev_tx) / 1024 / dt, 1)

            prev_ticks = cur_ticks
            prev_time = cur_time
            prev_rx, prev_tx = cur_rx, cur_tx

            async with SessionLocal() as session:
                await CiRepository(session).record_metrics(run_id, cpu_pct, rss_mb, rx_kbps, tx_kbps)

            metric_payload = json.dumps({
                "type": "metric",
                "cpu": cpu_pct,
                "rss": rss_mb,
                "rx": rx_kbps,
                "tx": tx_kbps,
                "ts": int(time.time()),
            })
            with contextlib.suppress(Exception):
                await cluster.client().publish(f"ci:run:{run_id}:stream", metric_payload)

    monitor_task = asyncio.create_task(_heartbeat_and_monitor())

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
                        asyncio.run_coroutine_threadsafe(
                            cluster.client().publish(
                                f"ci:run:{run_id}:stream",
                                json.dumps({"type": "log", "chunk": data.decode("utf-8", "replace")})
                            ),
                            loop,
                        )
                    except OSError:
                        break
                elif proc.poll() is not None:
                    break

    await loop.run_in_executor(None, _read_output)
    proc.wait()
    os.close(master_fd)
    monitor_task.cancel()
    return proc.returncode

async def execute_run(run_id: int) -> None:
    async with SessionLocal() as session:
        ci_repo = CiRepository(session)
        run = await ci_repo.get_run(run_id)
        if not run:
            return

    log_path = LOGS_DIR / f"{run_id}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"=== unsafie ci runner starting for {run.repo_full_name} @ {run.commit_sha[:8]} ===\n")

    check_run_id = await checks.create_check_run(
        run.installation_id,
        run.repo_full_name,
        run.commit_sha,
        run.id,
    )
    if check_run_id:
        async with SessionLocal() as session:
            await CiRepository(session).set_check_run_id(run.id, check_run_id)

    repo_cache = None
    try:
        repo_cache = await _sync_repo(run.installation_id, run.repo_full_name)
        ws = await _create_worktree(repo_cache, run.id, run.commit_sha)
    except Exception as e:
        logger.exception("ci preparation failed for run %s", run.id)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\nError during checkout: {e}\n")
        async with SessionLocal() as session:
            await CiRepository(session).finish_run(
                run.id, status="failure", exit_code=1, error_message=str(e), log_path=str(log_path),
            )
        if check_run_id:
            await checks.update_check_run(
                run.installation_id, run.repo_full_name, check_run_id,
                status="completed", conclusion="failure",
                title="Checkout Failed", summary=f"Error checking out repository: {e}",
            )
        return

    try:
        tool, has_ci, has_cd = await _discover_targets(ws)
        if not has_ci and not has_cd:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\nNo 'ci' or 'cd' target found in justfile or Makefile. Skipping.\n")
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(
                    run.id, status="success", exit_code=0, log_path=str(log_path),
                )
            if check_run_id:
                await checks.update_check_run(
                    run.installation_id, run.repo_full_name, check_run_id,
                    status="completed", conclusion="neutral",
                    title="No Targets Found", summary="Neither `justfile` nor `Makefile` had `ci` or `cd` targets.",
                )
            return

        base_env = os.environ.copy()
        base_env["CI"] = "true"
        base_env["UNSAFIE_CI"] = "true"
        base_env["GITHUB_SHA"] = run.commit_sha
        base_env["GITHUB_REF"] = run.ref
        base_env["GITHUB_BRANCH"] = run.branch
        base_env["GITHUB_REPOSITORY"] = run.repo_full_name

        if has_ci:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n>>> Running CI target ({tool} ci)\n")
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(run.id, status="in_progress", current_stage="ci")

            cmd = [tool, "ci"]
            code = await _run_command_pty(run.id, cmd, ws, base_env, log_path)
            if code != 0:
                async with SessionLocal() as session:
                    await CiRepository(session).finish_run(
                        run.id, status="failure", exit_code=code, current_stage="ci",
                        error_message=f"target 'ci' exited with code {code}", log_path=str(log_path),
                    )
                if check_run_id:
                    tail_log = ""
                    try:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            lines = f.readlines()
                            tail_log = "".join(lines[-40:])
                    except Exception:
                        pass
                    await checks.update_check_run(
                        run.installation_id, run.repo_full_name, check_run_id,
                        status="completed", conclusion="failure",
                        title="CI Failed",
                        summary=f"`{tool} ci` failed with exit code {code}",
                        text=f"```\n{tail_log}\n```",
                    )
                return

        if run.is_default_branch and has_cd:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n>>> Running CD target on default branch ({tool} cd)\n")
            async with SessionLocal() as session:
                await CiRepository(session).finish_run(run.id, status="in_progress", current_stage="cd")
                secrets = await CiRepository(session).get_secrets(run.repo_full_name)

            cd_env = base_env.copy()
            cd_env.update(secrets)

            cmd = [tool, "cd"]
            code = await _run_command_pty(run.id, cmd, ws, cd_env, log_path)
            if code != 0:
                async with SessionLocal() as session:
                    await CiRepository(session).finish_run(
                        run.id, status="failure", exit_code=code, current_stage="cd",
                        error_message=f"target 'cd' exited with code {code}", log_path=str(log_path),
                    )
                if check_run_id:
                    tail_log = ""
                    try:
                        with open(log_path, encoding="utf-8", errors="replace") as f:
                            lines = f.readlines()
                            tail_log = "".join(lines[-40:])
                    except Exception:
                        pass
                    await checks.update_check_run(
                        run.installation_id, run.repo_full_name, check_run_id,
                        status="completed", conclusion="failure",
                        title="CD Failed",
                        summary=f"`{tool} cd` failed with exit code {code}",
                        text=f"```\n{tail_log}\n```",
                    )
                return

        async with SessionLocal() as session:
            await CiRepository(session).finish_run(
                run.id, status="success", exit_code=0, log_path=str(log_path),
            )
        if check_run_id:
            summary = f"All targets passed successfully using `{tool}`."
            await checks.update_check_run(
                run.installation_id, run.repo_full_name, check_run_id,
                status="completed", conclusion="success",
                title="CI/CD Succeeded", summary=summary,
            )

    finally:
        if repo_cache:
            await _remove_worktree(repo_cache, run.id)
