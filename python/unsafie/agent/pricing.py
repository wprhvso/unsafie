import logging

logger = logging.getLogger(__name__)

MILLION = 1_000_000

PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.1-pro-preview": (1.25, 5.0),
    "gemini-3-flash-preview": (0.15, 0.6),
    "gemini-3.1-flash-lite": (0.075, 0.3),
    "gemini-2.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.15, 0.6),
}
FALLBACK = (0.5, 2.0)
COUNTERS = ("input_tokens", "output_tokens", "total_tokens")

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
    inputs = int(usage.get("input_tokens") or 0)
    output = int(usage.get("output_tokens") or 0)
    return (inputs * price_in + output * price_out) / MILLION


def merge(total: dict, usage: dict) -> dict:
    for key in COUNTERS:
        total[key] = int(total.get(key) or 0) + int((usage or {}).get(key) or 0)
    return total
