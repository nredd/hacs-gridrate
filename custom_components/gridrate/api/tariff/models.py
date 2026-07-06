"""Data model for utility tariffs.

Pure Python (no Home Assistant imports). A :class:`Tariff` is a small stack of
priced parts — per-kWh energy components, percent-of-subtotal surcharges, a
baseline (tier) policy, and fixed daily charges — organized into dated
:class:`TariffVersion` s so history replays with the rates that were in force
at the time. All money values are :class:`~decimal.Decimal` dollars.

Season and time-of-use resolution conventions:

- Seasons are date ranges in ``MM-DD`` terms, inclusive on both ends, and may
  wrap the year end (e.g. winter ``10-01`` → ``05-31``).
- TOU windows are daily ``[start_hour, end_hour)`` intervals; hours outside
  every window fall into ``default_period``.
- Rate tables are keyed ``season → period → $/kWh`` where ``"*"`` is a
  wildcard matching any season or period.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum

WILDCARD = "*"

type RateTable = dict[str, dict[str, Decimal]]
"""Per-kWh rates keyed ``season -> period -> $/kWh`` (``"*"`` wildcards)."""


class ComponentCategory(StrEnum):
    """What a per-kWh energy component pays for.

    Used for breakdown attribution (e.g. delivery vs generation vs the pile of
    per-kWh adders and credits riding along on the bill).
    """

    DELIVERY = "delivery"
    GENERATION = "generation"
    ADDER = "adder"


@dataclass(frozen=True, slots=True)
class TouWindow:
    """A daily time-of-use window: ``[start_hour, end_hour)`` local time."""

    period: str
    start_hour: int
    end_hour: int

    def __post_init__(self) -> None:
        """Validate the hour interval."""
        if not (0 <= self.start_hour < self.end_hour <= 24):
            msg = f"invalid TOU window hours [{self.start_hour}, {self.end_hour})"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Season:
    """A named seasonal date range, inclusive, possibly wrapping the year end."""

    name: str
    start_month: int
    start_day: int
    end_month: int
    end_day: int

    def contains(self, day: date) -> bool:
        """Return whether ``day`` falls inside this season."""
        start = (self.start_month, self.start_day)
        end = (self.end_month, self.end_day)
        key = (day.month, day.day)
        if start <= end:
            return start <= key <= end
        # Wraps the year end (e.g. Oct 1 - May 31).
        return key >= start or key <= end


@dataclass(frozen=True, slots=True)
class EnergyComponent:
    """A per-kWh priced component (rate may vary by season and TOU period)."""

    name: str
    category: ComponentCategory
    rates: RateTable

    def rate_for(self, season: str, period: str) -> Decimal:
        """Return the $/kWh rate for a season/period, honoring wildcards."""
        for season_key in (season, WILDCARD):
            periods = self.rates.get(season_key)
            if periods is None:
                continue
            for period_key in (period, WILDCARD):
                rate = periods.get(period_key)
                if rate is not None:
                    return rate
        msg = f"component {self.name!r} has no rate for ({season!r}, {period!r})"
        raise LookupError(msg)


@dataclass(frozen=True, slots=True)
class PercentSurcharge:
    """A surcharge computed as a percentage of the running subtotal.

    Surcharges apply sequentially in list order: each one's base includes the
    surcharges before it (this is how franchise-fee and local-tax lines
    compound on a real bill).
    """

    name: str
    percent: Decimal

    @property
    def fraction(self) -> Decimal:
        """Return the multiplier form of :attr:`percent` (``0.21% -> 0.0021``)."""
        return self.percent / Decimal(100)


@dataclass(frozen=True, slots=True)
class BaselinePolicy:
    """Baseline (tier) crediting: usage up to an allowance earns a credit.

    ``credit_per_kwh`` is the positive magnitude of the credit; the engine
    applies it as a negative amount on usage up to
    ``days x allowance_kwh_per_day[season]`` within each billing sub-period.
    """

    credit_per_kwh: Decimal
    allowance_kwh_per_day: dict[str, Decimal]

    def allowance_for(self, season: str, days: int) -> Decimal:
        """Return the baseline allowance in kWh for ``days`` days of ``season``."""
        per_day = self.allowance_kwh_per_day.get(
            season
        ) or self.allowance_kwh_per_day.get(WILDCARD)
        if per_day is None:
            msg = f"no baseline allowance for season {season!r}"
            raise LookupError(msg)
        return per_day * days


@dataclass(frozen=True, slots=True)
class FixedCharge:
    """A per-day fixed charge (e.g. a base services charge)."""

    name: str
    per_day: Decimal


@dataclass(frozen=True, slots=True)
class TariffVersion:
    """One dated revision of a tariff's rates and structure.

    ``effective_from`` is inclusive; ``effective_to`` is exclusive (``None``
    for the current revision).
    """

    effective_from: date
    effective_to: date | None = None
    seasons: tuple[Season, ...] = ()
    tou_windows: tuple[TouWindow, ...] = ()
    default_period: str = "off_peak"
    energy_components: tuple[EnergyComponent, ...] = ()
    percent_surcharges: tuple[PercentSurcharge, ...] = ()
    baseline: BaselinePolicy | None = None
    fixed_charges: tuple[FixedCharge, ...] = ()

    def covers(self, day: date) -> bool:
        """Return whether this version is in force on ``day``."""
        if day < self.effective_from:
            return False
        return self.effective_to is None or day < self.effective_to


@dataclass(frozen=True, slots=True)
class Tariff:
    """A utility rate plan: an ordered set of dated :class:`TariffVersion` s."""

    tariff_id: str
    name: str
    currency: str = "USD"
    versions: tuple[TariffVersion, ...] = field(default=())

    def version_for(self, day: date) -> TariffVersion:
        """Return the version in force on ``day``.

        Raises:
            LookupError: If no version covers ``day``.

        """
        for version in self.versions:
            if version.covers(day):
                return version
        msg = f"tariff {self.tariff_id!r} has no version covering {day.isoformat()}"
        raise LookupError(msg)
