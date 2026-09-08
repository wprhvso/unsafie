import time

from unsafie_cli import api, config
from unsafie_cli.errors import OK, CliError, NoAuth, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

WATCH_STEP = 5.0
WATCH_ROUNDS = 60


def _client(call: Call) -> api.Api:
    token = config.resolve("admin", call.options.token)
    if token is None:
        raise NoAuth(
            "no operator token",
            "unsafie config set admin <ADMIN_TOKEN>, the same one the admin panel uses",
        )
    base = config.resolve("api", call.options.api)
    return api.Api(base.value if base else config.DEFAULT_API, token.value, "/api/admin")


def _call(call: Call, method: str, path: str, body=None, params=None):
    return _client(call).call(method, path, body, params)


def donors(call: Call, out: Out) -> int:
    answer = _call(call, "GET", "/pool/donors")
    rows = answer.get("donors", [])
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("no donors — add one: unsafie admin donor add --token ghp_…")
        return OK
    out.table(
        [
            [
                row["login"],
                row["repo"],
                str(row["jobs"]),
                "on" if row["enabled"] else "off",
                row["state"],
                (row.get("last_error") or "")[:40],
            ]
            for row in rows
        ],
        ["login", "repo", "jobs", "enabled", "state", "last error"],
    )
    return OK


def donor_add(call: Call, out: Out) -> int:
    token = call.flag("token")
    if not token:
        raise Usage("no token", "unsafie admin donor add --token ghp_… --jobs 20")
    body = {
        "token": token,
        "jobs": int(call.flag("jobs") or "20"),
        "label": call.flag("label") or None,
    }
    answer = _call(call, "POST", "/pool/donors", body)
    donor = answer["donor"]
    out.send(
        answer,
        [
            f"donor {donor['login']} added, {donor['jobs']} jobs",
            f"worker token: {answer['worker_token']}",
            f"now: unsafie admin donor bootstrap {donor['login']}",
        ],
    )
    return OK


def donor_bootstrap(call: Call, out: Out) -> int:
    answer = _call(call, "POST", f"/pool/donors/{call.arg('login')}/bootstrap")
    out.send(answer, [f"{answer['repo']}@{answer['branch']}: {answer['workflow']} in place"])
    return OK


def donor_rotate(call: Call, out: Out) -> int:
    answer = _call(call, "POST", f"/pool/donors/{call.arg('login')}/rotate")
    out.send(answer, [answer["worker_token"], answer["next"]])
    return OK


def donor_disable(call: Call, out: Out) -> int:
    on = call.on("enable")
    answer = _call(call, "POST", f"/pool/donors/{call.arg('login')}/enable", None, {"on": on})
    out.send(answer, [f"{call.arg('login')}: {answer.get('detail')}"])
    return OK


def donor_rm(call: Call, out: Out) -> int:
    answer = _call(call, "DELETE", f"/pool/donors/{call.arg('login')}")
    out.send(answer, [f"{call.arg('login')} removed"])
    return OK


def donor_test(call: Call, out: Out) -> int:
    login = call.arg("login")
    answer = _call(call, "GET", "/pool/donors")
    found = next((row for row in answer.get("donors", []) if row["login"] == login), None)
    if found is None:
        raise CliError(f"no donor '{login}'")
    machines = _call(call, "GET", "/pool/machines")
    mine = [row for row in machines.get("machines", []) if row.get("donor_id") == found["id"]]
    out.send(
        {"donor": found, "machines": mine},
        [
            f"{login}: {found['state']}, {'enabled' if found['enabled'] else 'disabled'}",
            f"repo {found['repo']} · workflow {found['workflow']} · target {found['jobs']} jobs",
            f"machines alive from it: {len(mine)}",
            f"last error: {found.get('last_error') or 'none'}",
        ],
    )
    return OK


def _capacity_line(answer: dict) -> str:
    counts = answer.get("machines", {})
    return (
        f"idle {counts.get('idle', 0)} · leased {counts.get('leased', 0)} · "
        f"ci {counts.get('ci', 0)} · alive {counts.get('total', 0)} · "
        f"donors {answer.get('donors', 0)} · target {answer.get('target_jobs', 0)}"
    )


def capacity(call: Call, out: Out) -> int:
    if not call.on("watch"):
        answer = _call(call, "GET", "/pool/capacity")
        out.send(answer, [_capacity_line(answer)])
        return OK
    for _ in range(WATCH_ROUNDS):
        out.line(_capacity_line(_call(call, "GET", "/pool/capacity")))
        time.sleep(WATCH_STEP)
    return OK


def machines(call: Call, out: Out) -> int:
    answer = _call(call, "GET", "/pool/machines")
    rows = answer.get("machines", [])
    if call.flag("donor"):
        donors_answer = _call(call, "GET", "/pool/donors")
        wanted = {
            row["id"]
            for row in donors_answer.get("donors", [])
            if row["login"] == call.flag("donor")
        }
        rows = [row for row in rows if row.get("donor_id") in wanted]
    if out.json_mode:
        out.send({"machines": rows, "capacity": answer.get("capacity", {})})
        return OK
    if not rows:
        out.line("no machines alive")
        return OK
    out.table(
        [
            [
                row["name"],
                row.get("alias") or "—",
                row["state"],
                row["profile"],
                str(row.get("user_id") or "—"),
                f"{row.get('boot_seconds') or 0:.0f}s",
            ]
            for row in rows
        ],
        ["machine", "alias", "state", "profile", "user", "boot"],
    )
    return OK


def recycle(call: Call, out: Out) -> int:
    answer = _call(call, "POST", f"/pool/machines/{call.arg('name')}/recycle")
    out.send(answer, [f"{call.arg('name')}: {answer.get('detail')}"])
    return OK


def quota(call: Call, out: Out) -> int:
    user = call.arg("user")
    body = {
        "machines": int(call.flag("machines")) if call.flag("machines") else None,
        "background": int(call.flag("background")) if call.flag("background") else None,
        "minutes": int(call.flag("minutes")) if call.flag("minutes") else None,
        "machines_day": int(call.flag("machines-day")) if call.flag("machines-day") else None,
        "priority": int(call.flag("priority")) if call.flag("priority") else None,
        "blocked": True if call.on("block") else (False if call.on("unblock") else None),
    }
    if all(value is None for value in body.values()):
        answer = _call(call, "GET", "/pool/users")
        found = next(
            (row for row in answer.get("users", []) if str(row["user_id"]) == user), None
        )
        if found is None:
            raise CliError(f"user {user} has never used the pool")
        out.send(found, [str(found)])
        return OK
    answer = _call(call, "POST", f"/pool/users/{user}/quota", body)
    out.send(answer, [f"user {user}: {answer}"])
    return OK


def users(call: Call, out: Out) -> int:
    answer = _call(call, "GET", "/pool/users")
    rows = answer.get("users", [])
    if call.on("busy"):
        rows = [row for row in rows if row["machines_now"]]
    if out.json_mode:
        out.send({"users": rows})
        return OK
    if not rows:
        out.line("nobody is using the pool")
        return OK
    out.table(
        [
            [
                str(row["user_id"]),
                f"{row['machines_now']}/{row['max_machines']}",
                f"{row['minutes_today']:.0f}/{row['max_minutes_day']}",
                str(row["commands_today"]),
                str(row["priority"]),
                "blocked" if row["blocked"] else "",
            ]
            for row in rows
        ],
        ["user", "machines", "minutes today", "commands", "priority", ""],
    )
    return OK


def ci(call: Call, out: Out) -> int:
    action = call.arg("action")
    repo = call.arg("repo")
    if action in ("list", "ls", ""):
        answer = _call(call, "GET", "/pool/ci")
        rows = answer.get("repos", [])
        if out.json_mode:
            out.send(answer)
            return OK
        if not rows:
            out.line("no repositories on the pool")
            return OK
        out.table(
            [
                [
                    row["repo"],
                    str(row["user_id"]),
                    row["label"],
                    f"{row['runners']}/{row['jobs']}",
                    row["state"] + ("" if row["enabled"] else " (paused)"),
                ]
                for row in rows
            ],
            ["repo", "user", "label", "runners", "state"],
        )
        return OK
    if action not in ("pause", "resume", "block", "unblock"):
        raise Usage(
            f"unknown action '{action}'", "unsafie admin ci pause|resume|list owner/name"
        )
    if not repo:
        raise Usage("which repository?", "unsafie admin ci pause owner/name")
    on = action in ("resume", "unblock")
    answer = _call(call, "POST", f"/pool/ci/{repo}/enable", None, {"on": on})
    out.send(answer, [f"{repo}: {answer.get('detail')}"])
    return OK
