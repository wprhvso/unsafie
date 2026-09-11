import hashlib
import logging
import re
from dataclasses import dataclass

from unsafie.ssh.errors import SshError

logger = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
OPERATORS = ("==", "!=", ">=", "<=", "=", ">", "<")
NESTED_QUANTIFIER_RE1 = re.compile(r"(\+|\*|\{[0-9]+,?[0-9]*\})\s*(\+|\*|\{[0-9]+,?[0-9]*\})")
NESTED_QUANTIFIER_RE2 = re.compile(r"\([^)]*(\+|\*)[^)]*\)\s*(\+|\*|\{[0-9]+,?[0-9]*\})")


@dataclass(frozen=True)
class Condition:
    raw: str
    kind: str
    operator: str = ""
    number: float = 0.0
    needle: str = ""

    def describe(self) -> str:
        return self.raw


def parse(raw: str) -> Condition:
    text = (raw or "").strip()
    if not text:
        msg = "a condition is required"
        raise SshError(msg)
    low = text.lower()
    if low in ("changed", "change"):
        return Condition(text, "changed")
    if low in ("any", "always"):
        return Condition(text, "always")
    if low in ("empty", "!empty", "not empty"):
        return Condition(text, "empty" if low == "empty" else "not_empty")
    if low.startswith("exit"):
        rest = text[4:].strip()
        for op in OPERATORS:
            if rest.startswith(op):
                value = rest[len(op) :].strip()
                if not value.lstrip("-").isdigit():
                    msg = f"'{raw}': a number is expected after {op}"
                    raise SshError(msg)
                return Condition(text, "exit", "==" if op in ("=", "==") else op, float(value))
        msg = "'exit' needs a comparison, e.g. 'exit != 0'"
        raise SshError(msg)
    for prefix, kind in (
        ("contains:", "contains"),
        ("!contains:", "not_contains"),
        ("matches:", "matches"),
    ):
        if low.startswith(prefix):
            needle = text[len(prefix) :].strip()
            if not needle:
                msg = f"'{prefix}' needs text after it"
                raise SshError(msg)
            if kind == "matches":
                try:
                    re.compile(needle)
                except re.error as e:
                    msg = f"bad regular expression: {e}"
                    raise SshError(msg) from None
                if NESTED_QUANTIFIER_RE1.search(needle) or NESTED_QUANTIFIER_RE2.search(needle):
                    msg = f"'{needle}': nested quantifiers are not allowed"
                    raise SshError(msg)
            return Condition(text, kind, needle=needle)
    for op in OPERATORS:
        if text.startswith(op):
            value = text[len(op) :].strip().replace(",", ".")
            try:
                number = float(value)
            except ValueError:
                msg = f"'{raw}': a number is expected after {op}"
                raise SshError(msg) from None
            return Condition(text, "number", "==" if op in ("=", "==") else op, number)
    msg = (
        f"cannot parse the condition '{raw}'. Available: '>90', '<10', '=0', '==0', 'exit != 0', "
        "'contains:ERROR', '!contains:ok', 'matches:regex', 'changed', 'empty', 'any'"
    )
    raise SshError(
        msg,
    )


def _compare(op: str, left: float, right: float) -> bool:
    return {
        "==": left == right,
        "!=": left != right,
        ">": left > right,
        "<": left < right,
        ">=": left >= right,
        "<=": left <= right,
    }[op]


def first_number(text: str) -> float | None:
    m = NUMBER_RE.search(text or "")
    return float(m.group().replace(",", ".")) if m else None


def evaluate(
    condition: Condition, output: str, exit_code: int, previous: str | None,
) -> tuple[bool, str]:
    text = (output or "").strip()
    match condition.kind:
        case "always":
            return True, "always fires"
        case "changed":
            if previous is None:
                return False, "first run, nothing to compare with"
            current_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            prev_hash = (
                previous[7:]
                if previous.startswith("sha256:")
                else hashlib.sha256(previous.strip().encode("utf-8")).hexdigest()
            )
            changed = current_hash != prev_hash
            return changed, "the output has changed" if changed else "the output is the same"
        case "empty":
            return not text, "the output is empty" if not text else "there is output"
        case "not_empty":
            return bool(text), "there is output" if text else "the output is empty"
        case "exit":
            fires = _compare(condition.operator, float(exit_code), condition.number)
            return fires, f"exit={exit_code}"
        case "contains":
            fires = condition.needle.lower() in text.lower()
            return fires, f"{'found' if fires else 'no'} '{condition.needle}'"
        case "not_contains":
            fires = condition.needle.lower() not in text.lower()
            return fires, f"'{condition.needle}' is {'absent' if fires else 'present'}"
        case "matches":
            search_text = text[:50000]
            fires = re.search(condition.needle, search_text, re.MULTILINE) is not None
            return fires, f"regex {'matched' if fires else 'did not match'}"
        case "number":
            value = first_number(text)
            if value is None:
                return False, "no number in the output"
            fires = _compare(condition.operator, value, condition.number)
            return fires, f"{value:g} {condition.operator} {condition.number:g} is {fires}"
        case _:
            pass
    return False, "unknown condition"


def describe(watch, host, locale: str | None = None) -> str:
    state = "🔴" if watch.alerting else ("⏸" if not watch.enabled else "🟢")
    every = f"every {watch.interval_sec}s"
    tail = ""
    if watch.last_run_at:
        tail = f", last run {watch.last_run_at:%Y-%m-%d %H:%M}Z (exit={watch.last_exit})"
    if watch.fails:
        tail += f", {watch.fails} error(s) in a row"
    return (
        f"{state} [{watch.id}] {watch.name} · {host.alias} · {every} · {watch.condition}"
        f" · {watch.mode}{tail}\n    {watch.command}"
    )
