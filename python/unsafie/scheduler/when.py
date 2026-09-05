import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from unsafie.scheduler.cron import CronError

DURATION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([a-zа-я]+)", re.IGNORECASE)
UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "с": 1,
    "сек": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "м": 60,
    "мин": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
    "ч": 3600,
    "час": 3600,
    "часа": 3600,
    "часов": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "д": 86400,
    "дн": 86400,
    "день": 86400,
    "дня": 86400,
    "дней": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
    "н": 604800,
    "нед": 604800,
    "неделя": 604800,
    "недели": 604800,
}
MAX_DELAY = 366 * 86400
DAY_WORDS = (("послезавтра", 2), ("завтра", 1), ("сегодня", 0), ("tomorrow", 1), ("today", 0))
DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dt%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dt%H:%M:%S",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M",
    "%d.%m %H:%M",
)


class WhenError(ValueError):
    pass


def zone(name: str | None) -> ZoneInfo:
    name = (name or "UTC").strip()
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise WhenError(f"unknown timezone '{name}', use an IANA name like Europe/Moscow") from None


def duration(raw: str) -> int:
    raw = raw.strip().lower()
    if raw.isdigit():
        return int(raw) * 60
    total = 0.0
    pos = 0
    for m in DURATION_RE.finditer(raw):
        if raw[pos : m.start()].strip(" ,и"):
            raise WhenError(f"cannot parse duration '{raw}'")
        unit = m.group(2).lower()
        if unit not in UNITS:
            raise WhenError(f"unknown unit '{unit}' in '{raw}'; use s/m/h/d/w")
        total += float(m.group(1).replace(",", ".")) * UNITS[unit]
        pos = m.end()
    if pos == 0 or raw[pos:].strip():
        raise WhenError(f"cannot parse duration '{raw}', e.g. 45m, 2h30m, 1d")
    if total <= 0:
        raise WhenError("duration must be positive")
    if total > MAX_DELAY:
        raise WhenError("more than a year is too far")
    return int(total)


def absolute(raw: str, tz: ZoneInfo, now: datetime) -> datetime:
    s = raw.strip().lower()
    local_now = now.astimezone(tz)
    day_shift = 0
    for word, shift in DAY_WORDS:
        if s.startswith(word):
            s = s[len(word) :].strip(" ,в")
            day_shift = shift
            break
    if not s:
        raise WhenError("time is required, e.g. 'tomorrow 09:00'")
    parsed: datetime | None = None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%d.%m %H:%M":
            parsed = parsed.replace(year=local_now.year)
        break
    if parsed is None:
        for fmt in ("%H:%M", "%H:%M:%S", "%H"):
            try:
                t = datetime.strptime(s, fmt)
            except ValueError:
                continue
            parsed = local_now.replace(
                hour=t.hour, minute=t.minute, second=t.second, microsecond=0, tzinfo=None
            )
            if day_shift == 0 and parsed <= local_now.replace(tzinfo=None):
                day_shift = 1
            break
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.strip())
        except ValueError:
            raise WhenError(
                f"cannot parse '{raw}'; formats: 2026-09-03 18:00, 18:00, tomorrow 09:00"
            ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    parsed = parsed + timedelta(days=day_shift)
    result = parsed.astimezone(UTC)
    if result <= now:
        raise WhenError(f"{fmt_local(result, tz)} is in the past (now {fmt_local(now, tz)})")
    if result - now > timedelta(seconds=MAX_DELAY):
        raise WhenError("more than a year ahead is too far")
    return result


def fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return f"{local.strftime('%Y-%m-%d %H:%M')} {local.tzname() or tz.key}"


def humanize(seconds: int) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    parts = []
    for name, size in (("d", 86400), ("h", 3600), ("m", 60)):
        n, seconds = divmod(seconds, size)
        if n:
            parts.append(f"{n}{name}")
    return " ".join(parts) or "0m"


__all__ = ["CronError", "WhenError", "absolute", "duration", "fmt_local", "humanize", "zone"]
