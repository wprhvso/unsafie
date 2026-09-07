from unsafie_cli import api
from unsafie_cli.errors import OK, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call


def _seconds(value: str | None) -> int | None:
    if not value:
        return None
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    text = value.strip().lower()
    if text[-1] in units:
        head = text[:-1]
        if not head.replace(".", "", 1).isdigit():
            raise Usage(f"'{value}' is not a duration", "use 30s, 5m, 1h")
        return int(float(head) * units[text[-1]])
    if not text.isdigit():
        raise Usage(f"'{value}' is not a duration", "use 30s, 5m, 1h")
    return int(text)


def add(call: Call, out: Out) -> int:
    body = {
        "repo": call.arg("repo"),
        "label": call.flag("label") or None,
        "jobs": int(call.flag("jobs")) if call.flag("jobs") else None,
        "idle": _seconds(call.flag("idle")),
        "lifetime": _seconds(call.flag("lifetime")),
    }
    answer = api.client(call).call("POST", "/ci", body)
    repo = answer["repo"]
    out.send(
        answer,
        [
            f"{repo['repo']} runs on the pool, label {repo['label']}, up to {repo['jobs']} runners",
            "",
            answer["snippet"],
        ],
    )
    return OK


def listing(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/ci")
    rows = answer.get("repos", [])
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("no repositories on the pool — add one: unsafie ci add owner/name")
        return OK
    out.table(
        [
            [
                row["repo"],
                row["label"],
                str(row["jobs"]),
                row["state"] + ("" if row["enabled"] else " (paused)"),
                (row.get("last_error") or "")[:40],
            ]
            for row in rows
        ],
        ["repo", "label", "jobs", "state", "last error"],
    )
    return OK


def status(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", f"/ci/{call.arg('repo')}")
    if out.json_mode:
        out.send(answer)
        return OK
    repo = answer["repo"]
    runners = answer.get("runners", [])
    capacity = answer.get("capacity", {})
    out.line(out.bold(f"{repo['repo']} · label {repo['label']} · {repo['state']}"))
    out.line(f"runners now: {len(runners)} of {repo['jobs']} · pool idle: {capacity.get('idle', 0)}")
    if repo.get("last_error"):
        out.line(f"last error: {repo['last_error']}")
    recent = answer.get("recent", [])
    if recent:
        out.table(
            [
                [
                    row.get("runner") or "—",
                    row.get("machine") or "—",
                    row.get("status") or "",
                    row.get("result") or "",
                ]
                for row in recent
            ],
            ["runner", "machine", "status", "result"],
        )
    return OK


def logs(call: Call, out: Out) -> int:
    answer = api.client(call).call(
        "GET", f"/ci/{call.arg('repo')}/jobs", params={"limit": call.flag("limit", "50")}
    )
    if out.json_mode:
        out.send(answer)
        return OK
    rows = answer.get("jobs", [])
    if not rows:
        out.line("no runners have started for this repository yet")
        return OK
    out.table(
        [
            [
                row.get("started_at", "")[:19],
                row.get("runner") or "—",
                row.get("machine") or "—",
                row.get("status") or "",
                row.get("result") or "",
            ]
            for row in rows
        ],
        ["started", "runner", "machine", "status", "result"],
    )
    return OK


def snippet(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", f"/ci/{call.arg('repo')}/snippet")
    out.send(answer, [answer["snippet"]])
    return OK


def remove(call: Call, out: Out) -> int:
    answer = api.client(call).call("DELETE", f"/ci/{call.arg('repo')}")
    out.send(answer, [f"{answer['repo']} no longer runs on the pool"])
    return OK


def runner(call: Call, out: Out) -> int:
    from unsafie_cli.machine.ci_runner import run_runner

    config = call.flag("jit")
    if not config:
        raise Usage("no jit config", "the controller passes --jit; this is not a hand command")
    return run_runner(
        config,
        name=call.flag("name") or "",
        repo=call.flag("repo") or "",
        idle=float(call.flag("idle") or 300),
        lifetime=float(call.flag("lifetime") or 3600),
        out=out,
    )
