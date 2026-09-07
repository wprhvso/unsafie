import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from unsafie.database import SessionLocal
from unsafie.database.models.config import Config
from unsafie.database.models.credential import CredentialKind
from unsafie.database.repositories.turn import TurnRepository
from unsafie.database.repositories.user import UserRepository

UNITS_PER_USD = 10_000
MAX_UNITS = 10**15


def units_to_usd(units: int) -> Decimal:
    return Decimal(units) / UNITS_PER_USD


def usd_to_units(usd: Decimal) -> int:
    return int((usd * UNITS_PER_USD).to_integral_value(rounding=ROUND_HALF_UP))


def parse_usd(raw: str) -> int | None:
    """Dollars into units: '0.5', '0,5', '$0.5'. Anything negative means "no limit"."""
    cleaned = raw.replace(",", ".").replace("$", "").replace(" ", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -1 if value < 0 else min(usd_to_units(value), MAX_UNITS)


def ratio_for(config: Config, kind: str) -> float:
    return config.oauth_ratio if kind == CredentialKind.OAUTH else config.ratio


def charge_units(cost_usd: float | None, ratio: float) -> int:
    return math.ceil((cost_usd or 0) * ratio * UNITS_PER_USD)


@dataclass
class Hold:
    """Money reserved on the balance for as long as the turn runs."""

    user_id: int
    turn_id: UUID
    units: int
    balance: int

    def usd(self, ratio: float) -> float:
        """What is still reserved, as dollars the provider will bill at this ratio."""
        return self.units / UNITS_PER_USD / ratio

    async def spend(self, charge: int) -> int:
        """The money really left the balance: charge it and shrink the reservation."""
        async with SessionLocal() as session:
            user = await UserRepository(session).charge(self.user_id, charge)
            await TurnRepository(session).unhold(self.turn_id, min(charge, self.units))
        self.units = max(self.units - charge, 0)
        return user.balance

    async def release(self) -> None:
        """Whatever was not spent goes back to the balance."""
        units, self.units = self.units, 0
        if units <= 0:
            return
        async with SessionLocal() as session:
            await TurnRepository(session).unhold(self.turn_id, units)


@asynccontextmanager
async def hold(user_id: int, turn_id: UUID) -> AsyncIterator[Hold]:
    """Lock the whole per-turn budget upfront: the balance cannot go negative."""
    async with SessionLocal() as session:
        user = await UserRepository(session).get_or_create(user_id)
        reserved = await TurnRepository(session).hold(turn_id, user_id, user.budget)
    held = Hold(user_id, turn_id, reserved.units, reserved.balance)
    try:
        yield held
    finally:
        await held.release()
