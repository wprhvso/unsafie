import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from unsafie_cli import api, config
from unsafie_cli.errors import FAILED, NOT_FOUND, OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

FOLLOW_STEP = 2.0
FOLLOW_LIMIT = 3600.0
FINAL = ("done", "failed", "lost", "cancelled")


def _age(value: str | None) -> str:
    if not value:
        return "-"
    try:
        from datetime import datetime

        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    seconds = max(0.0, time.time() - moment.timestamp())
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    return f"{seconds / 3600:.1f}h"


def machines(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/pool/machines")
    mine = answer.get("machines", [])
    if not mine:
        capacity = answer.get("capacity", {})
        out.send(
            answer,
            [
                "no machines of yours",
                f"pool: {capacity.get('idle', 0)} idle of {capacity.get('total', 0)}",
                "take one: unsafie take",
            ],
        )
        return OK
    if out.json_mode:
        out.send(answer)
        return OK
    rows = [
        [
            item.get("alias") or item.get("name"),
            item.get("state", ""),
            item.get("profile", ""),
            _age(item.get("leased_at") or item.get("started_at")),
            str((item.get("facts") or {}).get("cpus") or "?") + " cpu",
        ]
        for item in mine
    ]
    out.table(rows, ["machine", "state", "profile", "held", "size"])
    return OK


def take(call: Call, out: Out) -> int:
    count = call.arg("count") or "1"
    if not count.isdigit():
        raise Usage("count must be a number", "unsafie take 3")
    body = {
        "count": int(count),
        "wait": float(call.flag("wait")) if call.flag("wait") else None,
        "turn": api.turn_of(),
    }
    answer = api.client(call).call("POST", "/pool/take", body, timeout=api.TIMEOUT * 3)
    taken = answer.get("machines", [])
    names = [item.get("alias") or item.get("name") for item in taken]
    out.send(answer, [f"took {', '.join(names)}"])
    return OK


def release(call: Call, out: Out) -> int:
    name = call.arg("name") or ("all" if call.on("all") else None)
    answer = api.client(call).call("POST", "/pool/release", {"machine": name})
    gone = answer.get("released", [])
    if not gone:
        out.send(answer, ["nothing to release"])
        return OK
    out.send(answer, [f"released {', '.join(gone)} — destroyed, nothing survives on them"])
    return OK


def rename(call: Call, out: Out) -> int:
    body = {"machine": call.arg("name"), "alias": call.arg("new")}
    answer = api.client(call).call("POST", "/pool/rename", body)
    out.send(answer, [f"{answer.get('machine')} is now {answer.get('alias')}"])
    return OK


def _run_once(call: Call, command: str, machine: str | None, timeout: float | None) -> dict:
    body = {
        "command": command,
        "machine": machine,
        "timeout": timeout,
        "cwd": call.flag("cwd") or None,
        "turn": api.turn_of(),
    }
    patience = (timeout or 600.0) + 60.0
    return api.client(call).call("POST", "/pool/run", body, timeout=patience)


def run(call: Call, out: Out) -> int:
    command = call.arg("command")
    if command == "-":
        command = sys.stdin.read()
    if not command.strip():
        raise Usage("nothing to run", "unsafie run 'uname -a' --on box-1")
    timeout = float(call.flag("timeout")) if call.flag("timeout") else None
    target = call.flag("on") or call.options.machine or None
    answer = _run_once(call, command, target, timeout)
    if answer.get("output"):
        out.send(answer, [str(answer["output"]).rstrip("\n")])
    elif out.json_mode:
        out.send(answer)
    code = answer.get("exit_code")
    if answer.get("truncated"):
        out.problem("output truncated")
    if code is None:
        out.problem(f"no exit code in {answer.get('seconds')}s: the command may still be running")
        return FAILED
    return int(code)


def fan(call: Call, out: Out) -> int:
    command = call.arg("command")
    listing = api.client(call).call("GET", "/pool/machines").get("machines", [])
    names = [item.get("alias") or item.get("name") for item in listing]
    if call.flag("on"):
        wanted = {piece.strip() for piece in call.flag("on").split(",") if piece.strip()}
        names = [name for name in names if name in wanted]
    if not names:
        raise CliError("no machines to run on", NOT_FOUND, "take some first: unsafie take 3")
    timeout = float(call.flag("timeout")) if call.flag("timeout") else None
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(len(names), 16)) as crew:
        futures = {
            crew.submit(_run_once, call, command, name, timeout): name for name in names
        }
        for future, name in futures.items():
            try:
                results[name] = future.result()
            except CliError as refused:
                results[name] = {"error": refused.message, "exit_code": None}
    if out.json_mode:
        out.send({"results": results})
        return OK
    worst = OK
    for name, answer in results.items():
        code = answer.get("exit_code")
        head = f"── {name} · exit={code if code is not None else answer.get('error', '?')}"
        out.line(out.bold(head))
        body = str(answer.get("output") or "").rstrip("\n")
        if body:
            out.line(body)
        if code is None or int(code) != 0:
            worst = FAILED
    return worst


def _split(reference: str) -> tuple[str | None, str]:
    machine, sep, path = reference.partition(":")
    if not sep or "/" in machine:
        return None, reference
    return machine, path


def cp(call: Call, out: Out) -> int:
    source_machine, source_path = _split(call.arg("source"))
    target_machine, target_path = _split(call.arg("target"))
    if source_machine is None and target_machine is None:
        raise Usage("at least one side must be a machine", "unsafie cp box-1:/tmp/a box-2:/tmp/a")
    key = f"cp/{int(time.time())}-{os.getpid()}"
    if source_machine is not None:
        answer = _run_once(call, f"unsafie blob put {key} {source_path}", source_machine, 300.0)
        _fail_if(answer, f"cannot read {source_path} on {source_machine}")
    else:
        client = api.client(call)
        client.raw("PUT", f"/blobs/{key}", open(source_path, "rb").read())
    if target_machine is not None:
        answer = _run_once(
            call, f"unsafie blob get {key} -o {target_path}", target_machine, 300.0
        )
        _fail_if(answer, f"cannot write {target_path} on {target_machine}")
    else:
        data = api.client(call).download(f"/blobs/{key}")
        with open(target_path, "wb") as handle:
            handle.write(data)
    api.client(call).call("DELETE", f"/blobs/{key}")
    out.send({"from": call.arg("source"), "to": call.arg("target")}, ["copied"])
    return OK


def _fail_if(answer: dict, message: str) -> None:
    if answer.get("exit_code") not in (0, None):
        raise CliError(f"{message}: {str(answer.get('output') or '').strip()[:200]}", FAILED)


def submit(call: Call, out: Out) -> int:
    command = call.arg("command")
    count = int(call.flag("count") or "1")
    client = api.client(call)
    started: list[str] = []
    for _ in range(max(1, min(count, 20))):
        body = {
            "command": command,
            "machine": call.options.machine or None,
            "background": True,
            "turn": api.turn_of(),
        }
        answer = client.call("POST", "/pool/run", body)
        started.append(str(answer.get("job")))
    out.send({"jobs": started}, [f"started {len(started)}: {' '.join(started)}"])
    return OK


def jobs(call: Call, out: Out) -> int:
    limit = call.flag("limit") or "20"
    answer = api.client(call).call("GET", "/pool/jobs", params={"limit": limit})
    rows = [
        [
            str(item.get("job"))[:8],
            item.get("machine", ""),
            item.get("status", ""),
            str(item.get("exit_code") if item.get("exit_code") is not None else "-"),
            _age(item.get("created_at")),
            str(item.get("command", ""))[:48],
        ]
        for item in answer.get("jobs", [])
    ]
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("no background jobs")
        return OK
    out.table(rows, ["job", "machine", "status", "exit", "age", "command"])
    return OK


def logs(call: Call, out: Out) -> int:
    job_id = call.arg("id")
    client = api.client(call)
    follow = call.on("follow")
    deadline = time.monotonic() + FOLLOW_LIMIT
    while True:
        answer = client.call(
            "GET",
            f"/pool/jobs/{job_id}",
            params={"wait": FOLLOW_STEP if follow else 0},
            timeout=FOLLOW_STEP + 60.0,
        )
        body = str(answer.get("output") or "")
        if body:
            out.line(body.rstrip("\n"))
        status = str(answer.get("status") or "")
        if not follow or status in FINAL or time.monotonic() > deadline:
            if out.json_mode:
                out.send(answer)
            code = answer.get("exit_code")
            return int(code) if isinstance(code, int) else OK


def cancel(call: Call, out: Out) -> int:
    answer = api.client(call).call("POST", f"/pool/jobs/{call.arg('id')}/cancel", {})
    out.send(answer, [f"{answer.get('job')}: {answer.get('status')}"])
    return OK


def serve(call: Call, out: Out) -> int:
    from unsafie_cli.machine import serve as run_machine

    token = call.flag("token") or os.environ.get("UNSAFIE_WORKER_TOKEN") or ""
    if not token:
        raise Usage(
            "no worker token",
            "pass --token or set UNSAFIE_WORKER_TOKEN; the donor repository has it as a secret",
        )
    base = config.resolve("api", call.options.api)
    out.line("serving as a machine of the pool")
    return run_machine(base.value if base else config.DEFAULT_API, token, call.flag("profile") or "fast")
