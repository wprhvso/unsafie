from collections import defaultdict
from uuid import UUID

INJECT_HEADER = (
    "While you were working, the user sent new messages (JSON, one per line). "
    "Take them into account as soon as possible: adjust the current task if they change it, "
    "and reply to them via send_message."
)

_pending: dict[UUID, list[str]] = defaultdict(list)


def enqueue(turn_id: UUID, prompt: str) -> int:
    _pending[turn_id].append(prompt)
    return len(_pending[turn_id])


def drain(turn_id: UUID) -> str | None:
    items = _pending.pop(turn_id, [])
    if not items:
        return None
    return INJECT_HEADER + "\n\n" + "\n".join(items)


def clear(turn_id: UUID) -> None:
    _pending.pop(turn_id, None)
