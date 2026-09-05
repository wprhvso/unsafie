from dataclasses import dataclass
from datetime import datetime, timedelta

MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
DAYS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}
ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
HORIZON_DAYS = 366 * 4


class CronError(ValueError):
    pass


def _value(s: str, lo: int, hi: int, names: dict[str, int] | None, raw: str) -> int:
    if names and s in names:
        v = names[s]
    elif s.isdigit():
        v = int(s)
    else:
        raise CronError(f"unknown value '{s}' in '{raw}'")
    if not lo <= v <= hi and not (names is DAYS and v == 7):
        raise CronError(f"{v} out of range {lo}-{hi} in '{raw}'")
    return v


def _parse_field(raw: str, lo: int, hi: int, names: dict[str, int] | None) -> tuple[set[int], bool]:
    out: set[int] = set()
    star = False
    for part in raw.split(","):
        part = part.strip().lower()
        if not part:
            raise CronError(f"empty element in '{raw}'")
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"bad step in '{raw}'")
            step = int(step_s)
        if part == "*":
            start, end = lo, hi
            star = star or step == 1
        else:
            a, b = part.split("-", 1) if "-" in part else (part, part)
            start, end = _value(a, lo, hi, names, raw), _value(b, lo, hi, names, raw)
            if "-" not in part and step > 1:
                end = hi
            if start > end:
                raise CronError(f"reversed range in '{raw}'")
        out.update(range(start, end + 1, step))
    return out, star


@dataclass(frozen=True)
class Cron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    dom_star: bool
    dow_star: bool

    def _day_ok(self, t: datetime) -> bool:
        if t.month not in self.months:
            return False
        dom = t.day in self.days
        dow = (t.isoweekday() % 7) in self.weekdays
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow
        if self.dow_star:
            return dom
        return dom or dow

    def next_after(self, after: datetime) -> datetime:
        t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = after + timedelta(days=HORIZON_DAYS)
        while t < limit:
            if not self._day_ok(t):
                t = (t + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if t.hour not in self.hours:
                t = (t + timedelta(hours=1)).replace(minute=0)
                continue
            if t.minute not in self.minutes:
                t += timedelta(minutes=1)
                continue
            return t
        raise CronError(f"'{self.expr}' never fires")


def parse(expr: str) -> Cron:
    expr = " ".join(expr.strip().split())
    expr = ALIASES.get(expr.lower(), expr)
    fields = expr.split(" ")
    if len(fields) != 5:
        raise CronError("cron takes 5 fields: minute hour day month weekday, e.g. '0 9 * * 1-5'")
    minutes, _ = _parse_field(fields[0], 0, 59, None)
    hours, _ = _parse_field(fields[1], 0, 23, None)
    days, dom_star = _parse_field(fields[2], 1, 31, None)
    months, _ = _parse_field(fields[3], 1, 12, MONTHS)
    weekdays, dow_star = _parse_field(fields[4], 0, 7, DAYS)
    if 7 in weekdays:
        weekdays = (weekdays - {7}) | {0}
    return Cron(
        expr,
        frozenset(minutes),
        frozenset(hours),
        frozenset(days),
        frozenset(months),
        frozenset(weekdays),
        dom_star,
        dow_star,
    )
