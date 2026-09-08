import json
import urllib.error
import urllib.request

from unsafie_cli import api
from unsafie_cli.errors import OK, CliError, Usage
from unsafie_cli.output import Out
from unsafie_cli.parser import Call

FETCH_LIMIT = 4_000_000


def schedule_add(call: Call, out: Out) -> int:
    body = {
        "text": call.arg("text"),
        "when": call.flag("when") or None,
        "cron": call.flag("cron") or None,
        "every": call.flag("every") or None,
        "task": call.on("task"),
    }
    if not any((body["when"], body["cron"], body["every"])):
        raise Usage("when, cron or every is required", "unsafie schedule add 'ping' --every 6h")
    answer = api.client(call).call("POST", "/schedule", body)
    task = answer["task"]
    out.send(answer, [f"[{task['id']}] next at {task['next_run_at']}"])
    return OK


def schedule_list(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/schedule")
    rows = answer.get("tasks", [])
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("nothing is scheduled")
        return OK
    out.table(
        [
            [
                str(row["id"]),
                row["kind"],
                str(row["next_run_at"])[:19],
                row["cron"] or (f"every {row['every']}s" if row["every"] else "once"),
                "on" if row["enabled"] else "paused",
                row["text"][:40],
            ]
            for row in rows
        ],
        ["id", "kind", "next", "repeat", "state", "text"],
    )
    return OK


def schedule_rm(call: Call, out: Out) -> int:
    client = api.client(call)
    if call.on("all"):
        gone = 0
        for row in client.call("GET", "/schedule").get("tasks", []):
            client.call("DELETE", f"/schedule/{row['id']}")
            gone += 1
        out.send({"removed": gone}, [f"removed {gone}"])
        return OK
    answer = client.call("DELETE", f"/schedule/{call.arg('id')}")
    out.send(answer, [f"task {call.arg('id')} removed"])
    return OK


def schedule_pause(call: Call, out: Out) -> int:
    on = call.on("resume")
    answer = api.client(call).call("POST", f"/schedule/{call.arg('id')}/pause", None, {"on": on})
    out.send(answer, [f"task {call.arg('id')} {'resumed' if on else 'paused'}"])
    return OK


def watch_add(call: Call, out: Out) -> int:
    body = {
        "name": call.arg("name"),
        "command": call.flag("cmd"),
        "condition": call.flag("if"),
        "every": call.flag("every") or "5m",
        "host": call.flag("host") or None,
        "task": call.on("task"),
    }
    if not body["command"] or not body["condition"]:
        raise Usage(
            "a watch needs a command and a condition",
            "unsafie watch add disk --cmd 'df -h /' --if '>90' --every 5m",
        )
    answer = api.client(call).call("POST", "/watch", body)
    watch = answer["watch"]
    out.send(answer, [f"[{watch['id']}] {watch['name']} on {watch['host']} every {watch['every']}s"])
    return OK


def watch_list(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/watch")
    rows = answer.get("watches", [])
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("nothing is watched")
        return OK
    out.table(
        [
            [
                str(row["id"]),
                row["name"],
                row["host"] or "—",
                row["condition"],
                f"{row['every']}s",
                "alerting" if row["alerting"] else ("on" if row["enabled"] else "paused"),
            ]
            for row in rows
        ],
        ["id", "name", "host", "condition", "every", "state"],
    )
    return OK


def watch_run(call: Call, out: Out) -> int:
    answer = api.client(call).call("POST", f"/watch/{call.arg('id')}/run", {})
    out.send(
        answer,
        [
            f"exit={answer.get('exit_code')} · {'fires' if answer.get('fires') else 'quiet'} · "
            f"{answer.get('reason')}",
            str(answer.get("output") or "").rstrip(),
        ],
    )
    return OK


def watch_rm(call: Call, out: Out) -> int:
    client = api.client(call)
    if call.on("all"):
        gone = 0
        for row in client.call("GET", "/watch").get("watches", []):
            client.call("DELETE", f"/watch/{row['id']}")
            gone += 1
        out.send({"removed": gone}, [f"removed {gone}"])
        return OK
    answer = client.call("DELETE", f"/watch/{call.arg('id')}")
    out.send(answer, [f"watch {call.arg('id')} removed"])
    return OK


def sub_add(call: Call, out: Out) -> int:
    filters = call.flag("filters")
    if filters:
        try:
            json.loads(filters)
        except ValueError:
            raise Usage("--filters must be json", '--filters \'{"branch":"main"}\'') from None
    body = {
        "kind": call.arg("kind"),
        "repo": call.flag("repo"),
        "filters": json.loads(filters) if filters else None,
    }
    if not body["repo"]:
        raise Usage("which repository?", "unsafie sub add ci --repo owner/name")
    answer = api.client(call).call("POST", "/subs", body)
    out.send(answer, [f"[{answer['id']}] {answer['kind']} of {answer['repo']} goes to this chat"])
    return OK


def sub_list(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/subs")
    rows = answer.get("subs", [])
    if out.json_mode:
        out.send(answer)
        return OK
    if not rows:
        out.line("this chat is subscribed to nothing")
        return OK
    out.table(
        [[str(row["id"]), row["kind"], row["repo"], json.dumps(row["filters"] or {})] for row in rows],
        ["id", "kind", "repo", "filters"],
    )
    return OK


def sub_rm(call: Call, out: Out) -> int:
    client = api.client(call)
    if call.on("all"):
        gone = 0
        for row in client.call("GET", "/subs").get("subs", []):
            client.call("DELETE", f"/subs/{row['id']}")
            gone += 1
        out.send({"removed": gone}, [f"removed {gone}"])
        return OK
    answer = client.call("DELETE", f"/subs/{call.arg('id')}")
    out.send(answer, [f"subscription {call.arg('id')} removed"])
    return OK


def tz_get(call: Call, out: Out) -> int:
    answer = api.client(call).call("GET", "/tz")
    out.send(answer, [answer["timezone"]])
    return OK


def tz_set(call: Call, out: Out) -> int:
    answer = api.client(call).call("POST", "/tz", None, {"zone": call.arg("zone")})
    out.send(answer, [f"timezone is {answer['timezone']}"])
    return OK


def fetch(call: Call, out: Out) -> int:
    url = call.arg("url")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    timeout = float(call.flag("timeout") or "30")
    request = urllib.request.Request(url, headers={"User-Agent": "unsafie-cli"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            kind = answer.headers.get_content_type()
            raw = answer.read(FETCH_LIMIT)
    except urllib.error.HTTPError as refused:
        raise CliError(f"{url} answered {refused.code}") from None
    except (urllib.error.URLError, TimeoutError) as unreachable:
        raise CliError(f"{url} is not answering: {unreachable}") from None
    body = raw.decode(errors="replace")
    if call.on("json") or kind.endswith("json"):
        try:
            out.send(json.loads(body))
            return OK
        except ValueError:
            pass
    if kind.startswith("text/html") and not call.on("json"):
        from unsafie_cli.commands.chrome import _to_markdown

        body = _to_markdown(body)
    out.line(body.rstrip())
    return OK
