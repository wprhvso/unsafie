import math

from unsafie.database.models.config import Config
from unsafie.database.models.credential import CredentialKind

UNITS_PER_USD = 10_000


def ratio_for(config: Config, kind: str) -> float:
    return config.oauth_ratio if kind == CredentialKind.OAUTH else config.ratio


def budget_usd(balance: int, user_budget: int, ratio: float) -> float:
    cap = balance if user_budget < 0 else min(balance, user_budget)
    return cap / UNITS_PER_USD / ratio


def charge_units(cost_usd: float | None, ratio: float) -> int:
    return math.ceil((cost_usd or 0) * ratio * UNITS_PER_USD)
