"""Self-calibration: derive tariff parameters from utility hourly reads.

Pure Python (no Home Assistant imports). Utilities expose hourly *billed*
cost/usage through Opower, and the hourly unit rate (cost ÷ usage) takes only
a handful of values: the time-of-use delivery rate for the hour's period, at
either the tier-2 level or the tier-1 level (tier 2 minus the baseline
credit). That structure makes the tariff recoverable from data:

- **TOU windows** — hours of day whose median unit rate sits at an elevated
  level form the peak window.
- **Delivery rates** — the upper (tier-2) unit-rate level per period.
- **Baseline credit** — the gap between the two unit-rate levels.
- **Billing-cycle starts** — days where the unit-rate level falls back from
  tier 2 to tier 1 (the allowance resets).
- **Baseline allowance** — cumulative kWh from a cycle start to its first
  tier-2 hour, divided by the days elapsed.

Feed :func:`derive` a *single rate regime* (one season, one tariff revision —
slice multi-season reads by the configured tariff's seasons first), then
compare against the configured tariff with :func:`drift_report`.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from statistics import median
from typing import TYPE_CHECKING

from custom_components.gridrate.api.tariff.models import WILDCARD

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date, datetime

    from custom_components.gridrate.api.tariff.models import TariffVersion

RATE_PLACES = Decimal("0.00001")
# Minimum kWh in an hour for its unit rate to be trusted (tiny denominators
# amplify the utility's cent-level cost rounding into rate noise).
MIN_KWH = 0.25
# Minimum $/kWh separation to consider two clusters distinct rate levels.
LEVEL_GAP = 0.015


@dataclass(frozen=True, slots=True)
class HourlyRead:
    """One hour of billed usage and cost, in utility-local time."""

    start: datetime
    kwh: float
    cost: float

    @property
    def unit_rate(self) -> float:
        """Return the billed $/kWh for this hour."""
        return self.cost / self.kwh


@dataclass(frozen=True, slots=True)
class DerivedPeriodRates:
    """The unit-rate levels observed for one TOU period."""

    period: str
    tier1_rate: Decimal | None
    tier2_rate: Decimal | None

    @property
    def credit(self) -> Decimal | None:
        """Return the tier gap (the baseline credit), when both tiers appear."""
        if self.tier1_rate is None or self.tier2_rate is None:
            return None
        return self.tier2_rate - self.tier1_rate


@dataclass(frozen=True, slots=True)
class DerivedTariff:
    """Tariff parameters recovered from hourly reads of one rate regime."""

    peak_window: tuple[int, int] | None
    """Peak hours as ``[start_hour, end_hour)``, or ``None`` if flat-rate."""
    period_rates: dict[str, DerivedPeriodRates]
    baseline_credit: Decimal | None
    cycle_starts: tuple[date, ...]
    allowance_kwh_per_day: Decimal | None
    read_count: int

    def delivery_rate(self, period: str) -> Decimal | None:
        """Return the derived tier-2 delivery rate for a period.

        Falls back to tier-1 plus the derived credit when the account never
        exceeded its baseline in the observed window.
        """
        rates = self.period_rates.get(period)
        if rates is None:
            return None
        if rates.tier2_rate is not None:
            return rates.tier2_rate
        if rates.tier1_rate is not None and self.baseline_credit is not None:
            return rates.tier1_rate + self.baseline_credit
        return None


@dataclass(frozen=True, slots=True)
class DriftItem:
    """One derived-vs-configured discrepancy."""

    field: str
    configured: Decimal | None
    derived: Decimal | None
    tolerance: Decimal

    @property
    def delta(self) -> Decimal | None:
        """Return derived minus configured, when both are known."""
        if self.configured is None or self.derived is None:
            return None
        return self.derived - self.configured

    @property
    def exceeded(self) -> bool:
        """Return whether the delta exceeds this item's tolerance."""
        return self.delta is not None and abs(self.delta) > self.tolerance


@dataclass(frozen=True, slots=True)
class DriftReport:
    """Comparison of a derivation against the configured tariff."""

    items: tuple[DriftItem, ...]

    @property
    def drifted(self) -> tuple[DriftItem, ...]:
        """Return the items whose delta exceeds their tolerance."""
        return tuple(item for item in self.items if item.exceeded)

    @property
    def has_drift(self) -> bool:
        """Return whether any item drifted beyond its tolerance."""
        return bool(self.drifted)


def _quantize(value: float) -> Decimal:
    """Convert a float rate to a 5-decimal-place Decimal."""
    return Decimal(str(value)).quantize(RATE_PLACES)


def _aggregate_rate(reads: Sequence[HourlyRead]) -> float:
    """Return total cost over total kWh (cancels per-hour cost rounding)."""
    return sum(read.cost for read in reads) / sum(read.kwh for read in reads)


def _split_levels(reads: Sequence[HourlyRead]) -> tuple[float | None, float | None]:
    """Split reads into (tier1, tier2) rate levels at the largest unit-rate gap.

    Returns a single level as tier 1 with tier 2 ``None`` when the values
    don't separate into two clusters. Each level's rate is the cluster's
    aggregate cost ÷ kWh, which is far less sensitive to the utility's
    per-hour cost rounding than a median of ratios.
    """
    if not reads:
        return (None, None)
    ordered = sorted(reads, key=lambda read: read.unit_rate)
    gaps = [
        (ordered[i + 1].unit_rate - ordered[i].unit_rate, i)
        for i in range(len(ordered) - 1)
    ]
    if not gaps:
        return (ordered[0].unit_rate, None)
    largest_gap, split_at = max(gaps)
    if largest_gap < LEVEL_GAP:
        return _aggregate_rate(ordered), None
    return (
        _aggregate_rate(ordered[: split_at + 1]),
        _aggregate_rate(ordered[split_at + 1 :]),
    )


def _detect_peak_window(reads: Iterable[HourlyRead]) -> tuple[int, int] | None:
    """Find the contiguous run of hours priced at an elevated level."""
    by_hour: dict[int, list[float]] = {}
    for read in reads:
        by_hour.setdefault(read.start.hour, []).append(read.unit_rate)
    medians = {hour: median(rates) for hour, rates in by_hour.items()}
    if len(medians) < 2:
        return None
    low, high = min(medians.values()), max(medians.values())
    if high - low < LEVEL_GAP:
        return None
    threshold = (low + high) / 2
    peak_hours = sorted(hour for hour, rate in medians.items() if rate > threshold)
    if not peak_hours:
        return None
    # Require contiguity; a fragmented "window" means the detection failed.
    if peak_hours != list(range(peak_hours[0], peak_hours[-1] + 1)):
        return None
    return peak_hours[0], peak_hours[-1] + 1


def _daily_tiers(
    reads: Sequence[HourlyRead],
    period_rates: dict[str, DerivedPeriodRates],
    peak_window: tuple[int, int] | None,
) -> dict[date, int]:
    """Classify each day as tier 1 or tier 2 by its hours' rate levels."""
    tiers: dict[date, list[int]] = {}
    for read in reads:
        period = _period_of(read, peak_window)
        rates = period_rates[period]
        if rates.tier1_rate is None or rates.tier2_rate is None:
            continue
        midpoint = float(rates.tier1_rate + rates.tier2_rate) / 2
        tiers.setdefault(read.start.date(), []).append(
            2 if read.unit_rate > midpoint else 1
        )
        # Note: 2 and 1 are tier numbers, not magic thresholds.
    return {day: max(hour_tiers) for day, hour_tiers in tiers.items()}


def _period_of(read: HourlyRead, peak_window: tuple[int, int] | None) -> str:
    """Return the TOU period name for a read given the detected window."""
    if peak_window is not None and peak_window[0] <= read.start.hour < peak_window[1]:
        return "peak"
    return "off_peak"


def derive(reads: Sequence[HourlyRead]) -> DerivedTariff:
    """Recover tariff parameters from hourly reads of a single rate regime.

    Reads with less than ``MIN_KWH`` consumption are ignored (cent-level cost
    rounding makes their unit rates unreliable).
    """
    usable = sorted(
        (read for read in reads if read.kwh >= MIN_KWH), key=lambda r: r.start
    )
    if not usable:
        return DerivedTariff(
            peak_window=None,
            period_rates={},
            baseline_credit=None,
            cycle_starts=(),
            allowance_kwh_per_day=None,
            read_count=0,
        )

    peak_window = _detect_peak_window(usable)

    by_period: dict[str, list[HourlyRead]] = {}
    for read in usable:
        by_period.setdefault(_period_of(read, peak_window), []).append(read)

    period_rates: dict[str, DerivedPeriodRates] = {}
    tier_gaps: list[Decimal] = []
    for period, period_reads in by_period.items():
        tier1, tier2 = _split_levels(period_reads)
        derived = DerivedPeriodRates(
            period=period,
            tier1_rate=_quantize(tier1) if tier1 is not None else None,
            tier2_rate=_quantize(tier2) if tier2 is not None else None,
        )
        period_rates[period] = derived
        if (credit := derived.credit) is not None:
            tier_gaps.append(credit)

    baseline_credit = (
        _quantize(float(median(float(gap) for gap in tier_gaps))) if tier_gaps else None
    )

    # Cycle boundaries: a day whose tier falls back to 1 after a tier-2 day
    # starts a new billing cycle (the baseline allowance reset).
    day_tiers = _daily_tiers(usable, period_rates, peak_window)
    days = sorted(day_tiers)
    cycle_starts = tuple(
        day
        for prev, day in pairwise(days)
        if day_tiers[prev] == 2 and day_tiers[day] == 1
    )

    # Allowance: kWh accumulated from a cycle start until the first tier-2
    # day, spread over the elapsed days.
    allowance_estimates: list[float] = []
    kwh_by_day: dict[date, float] = {}
    for read in usable:
        kwh_by_day[read.start.date()] = kwh_by_day.get(read.start.date(), 0.0) + read.kwh
    for start_day in cycle_starts:
        cumulative = 0.0
        for day in days:
            if day < start_day:
                continue
            if day_tiers[day] == 2:
                elapsed = (day - start_day).days
                if elapsed > 0:
                    allowance_estimates.append(cumulative / elapsed)
                break
            cumulative += kwh_by_day.get(day, 0.0)

    return DerivedTariff(
        peak_window=peak_window,
        period_rates=period_rates,
        baseline_credit=baseline_credit,
        cycle_starts=cycle_starts,
        allowance_kwh_per_day=(
            _quantize(median(allowance_estimates)) if allowance_estimates else None
        ),
        read_count=len(usable),
    )


def drift_report(
    derived: DerivedTariff,
    version: TariffVersion,
    season: str,
    *,
    rate_tolerance: Decimal = Decimal("0.005"),
    allowance_tolerance: Decimal = Decimal("1.0"),
) -> DriftReport:
    """Compare a derivation against the configured tariff version.

    Checks the delivery energy rates per TOU period, the baseline credit
    (``rate_tolerance``, $/kWh), and the baseline allowance
    (``allowance_tolerance``, kWh/day — the estimate is coarser). Anything
    beyond tolerance counts as drift: a utility rate change the configured
    tariff hasn't caught up with.
    """
    items: list[DriftItem] = []

    delivery = next(
        (
            component
            for component in version.energy_components
            if component.category.value == "delivery"
        ),
        None,
    )
    periods = {window.period for window in version.tou_windows} | {version.default_period}
    for period in sorted(periods):
        configured: Decimal | None = None
        if delivery is not None:
            try:
                configured = delivery.rate_for(season, period)
            except LookupError:
                configured = None
        items.append(
            DriftItem(
                field=f"delivery_energy.{period}",
                configured=configured,
                derived=derived.delivery_rate(period),
                tolerance=rate_tolerance,
            )
        )

    configured_credit = (
        version.baseline.credit_per_kwh if version.baseline is not None else None
    )
    items.append(
        DriftItem(
            field="baseline_credit",
            configured=configured_credit,
            derived=derived.baseline_credit,
            tolerance=rate_tolerance,
        )
    )

    if version.baseline is not None:
        allowance = version.baseline.allowance_kwh_per_day.get(
            season
        ) or version.baseline.allowance_kwh_per_day.get(WILDCARD)
        items.append(
            DriftItem(
                field="baseline_allowance_kwh_per_day",
                configured=allowance,
                derived=derived.allowance_kwh_per_day,
                tolerance=allowance_tolerance,
            )
        )

    return DriftReport(items=tuple(items))
