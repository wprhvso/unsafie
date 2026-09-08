from unsafie_sdk.client import client


def schedule(text: str, *, when: str | None = None, cron: str | None = None,
             every: str | None = None, task: bool = False) -> dict:
    """Say or do something later: when='18:00', cron='0 9 * * 1-5', every='6h'.

    task=True wakes the agent with this text instead of just sending it.
    """
    body = {"text": text, "when": when, "cron": cron, "every": every, "task": task}
    return client().call("POST", "/schedule", body)["task"]


def schedules() -> list[dict]:
    """Everything scheduled in this chat."""
    return client().call("GET", "/schedule").get("tasks", [])


def unschedule(task_id: int) -> dict:
    """Delete a scheduled task."""
    return client().call("DELETE", f"/schedule/{task_id}")


def pause(task_id: int, on: bool = False) -> dict:
    """Pause or resume a scheduled task."""
    return client().call("POST", f"/schedule/{task_id}/pause", None, {"on": on})


def watch(name: str, command: str, condition: str, *, every: str = "5m",
          host: str | None = None, task: bool = False) -> dict:
    """Watch a command on a server and report when the condition turns.

    Conditions: '>90', '<10', '=0', 'exit != 0', 'contains:ERROR', '!contains:ok',
    'matches:regex', 'changed', 'empty', 'any'.
    """
    body = {
        "name": name,
        "command": command,
        "condition": condition,
        "every": every,
        "host": host,
        "task": task,
    }
    return client().call("POST", "/watch", body)["watch"]


def watches() -> list[dict]:
    """What is being watched."""
    return client().call("GET", "/watch").get("watches", [])


def run_watch(watch_id: int) -> dict:
    """Run a watch right now without waiting for its schedule."""
    return client().call("POST", f"/watch/{watch_id}/run", {})


def unwatch(watch_id: int) -> dict:
    """Delete a watch."""
    return client().call("DELETE", f"/watch/{watch_id}")


def subscribe(kind: str, repo: str, **filters) -> dict:
    """Send repository events to this chat: ci, push, pr, issues, releases, stars…"""
    return client().call("POST", "/subs", {"kind": kind, "repo": repo, "filters": filters or None})


def subscriptions() -> list[dict]:
    """What this chat is subscribed to."""
    return client().call("GET", "/subs").get("subs", [])


def unsubscribe(sub_id: int) -> dict:
    """Stop sending those events here."""
    return client().call("DELETE", f"/subs/{sub_id}")


def timezone(zone: str | None = None) -> str:
    """Read the timezone of this user, or set it."""
    if zone is None:
        return str(client().call("GET", "/tz")["timezone"])
    return str(client().call("POST", "/tz", None, {"zone": zone})["timezone"])
