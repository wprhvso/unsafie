import logging

logger = logging.getLogger(__name__)

MILLION = 1_000_000
CACHE_WRITE_5M = 1.25
CACHE_WRITE_1H = 2.0
CACHE_READ = 0.1

PRICES: dict[str, tuple[float, float]] = {
    "claude-mythos-5": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
FALLBACK = (5.0, 25.0)
COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

_unpriced: set[str] = set()


def rates(model: str) -> tuple[float, float]:
    best = ""
    for prefix in PRICES:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    if best:
        return PRICES[best]
    if model not in _unpriced:
        _unpriced.add(model)
        logger.warning("no price for %s, billing it as %s/%s per MTok", model, *FALLBACK)
    return FALLBACK


def cost(model: str, usage: dict) -> float:
    if not usage:
        return 0.0
    price_in, price_out = rates(model)
    breakdown = usage.get("cache_creation") or {}
    write_5m = int(breakdown.get("ephemeral_5m_input_tokens") or 0)
    write_1h = int(breakdown.get("ephemeral_1h_input_tokens") or 0)
    if not (write_5m or write_1h):
        write_1h = int(usage.get("cache_creation_input_tokens") or 0)
    billable = (
        int(usage.get("input_tokens") or 0)
        + write_5m * CACHE_WRITE_5M
        + write_1h * CACHE_WRITE_1H
        + int(usage.get("cache_read_input_tokens") or 0) * CACHE_READ
    )
    output = int(usage.get("output_tokens") or 0)
    return billable * price_in / MILLION + output * price_out / MILLION


def merge(total: dict, usage: dict) -> dict:
    for key in COUNTERS:
        total[key] = int(total.get(key) or 0) + int((usage or {}).get(key) or 0)
    return total
