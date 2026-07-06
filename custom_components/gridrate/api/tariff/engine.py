"""Tariff evaluation: marginal rates and billing-cycle replay.

Pure Python (no Home Assistant imports). Two entry points:

- :func:`marginal_rate` — the full marginal $/kWh at a moment in time, with a
  per-component breakdown (what one more kWh costs right now).
- :func:`compute_bill` — replay a billing cycle's daily usage into line items
  and a total, using each line's in-force tariff version and the utility's
  own arithmetic (per-line cent rounding, per-sub-period baseline crediting,
  sequential percent surcharges).

A "tariff stack" is simply a sequence of :class:`~.models.Tariff` — e.g. a
utility delivery tariff plus a CCA generation tariff — evaluated together.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import groupby
from typing import TYPE_CHECKING

from custom_components.gridrate.api.tariff.models import Season, Tariff, TariffVersion

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date, datetime

CENT = Decimal("0.01")


def _to_cents(amount: Decimal) -> Decimal:
    """Round to whole cents the way utility bills print lines."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def season_for(version: TariffVersion, day: date) -> Season:
    """Return the season ``day`` falls in for ``version``.

    Raises:
        LookupError: If no season covers ``day``.

    """
    for season in version.seasons:
        if season.contains(day):
            return season
    msg = f"no season covers {day.isoformat()}"
    raise LookupError(msg)


def period_for(version: TariffVersion, when: datetime) -> str:
    """Return the TOU period name in force at ``when`` (local time)."""
    for window in version.tou_windows:
        if window.start_hour <= when.hour < window.end_hour:
            return window.period
    return version.default_period


@dataclass(frozen=True, slots=True)
class RateBreakdown:
    """The marginal $/kWh at a moment, broken down by component."""

    total: Decimal
    components: dict[str, Decimal]
    season: str
    period: str
    over_baseline: bool


def marginal_rate(
    tariffs: Sequence[Tariff],
    when: datetime,
    *,
    over_baseline: bool = False,
) -> RateBreakdown:
    """Return the full marginal $/kWh across a tariff stack at ``when``.

    Sums every per-kWh energy component in force, applies the baseline credit
    unless ``over_baseline``, then compounds percent surcharges sequentially
    on the marginal amount. Fixed daily charges are not part of a marginal
    rate and are excluded.
    """
    components: dict[str, Decimal] = {}
    subtotal = Decimal(0)
    for tariff in tariffs:
        version = tariff.version_for(when.date())
        season = season_for(version, when.date())
        period = period_for(version, when)
        for component in version.energy_components:
            rate = component.rate_for(season.name, period)
            components[component.name] = rate
            subtotal += rate
        if version.baseline is not None and not over_baseline:
            credit = -version.baseline.credit_per_kwh
            components["baseline_credit"] = credit
            subtotal += credit
        for surcharge in version.percent_surcharges:
            amount = subtotal * surcharge.fraction
            components[surcharge.name] = amount
            subtotal += amount

    # Season/period reported from the first tariff in the stack (the stack
    # shares one clock; the delivery tariff is canonical).
    head = tariffs[0].version_for(when.date())
    return RateBreakdown(
        total=subtotal,
        components=components,
        season=season_for(head, when.date()).name,
        period=period_for(head, when),
        over_baseline=over_baseline,
    )


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """One day's energy use in kWh, split by TOU period name."""

    day: date
    kwh_by_period: dict[str, Decimal]

    @property
    def total_kwh(self) -> Decimal:
        """Return the day's total kWh across all periods."""
        return sum(self.kwh_by_period.values(), Decimal(0))


@dataclass(frozen=True, slots=True)
class LineItem:
    """One computed bill line, rounded to cents like the printed bill."""

    tariff_id: str
    component: str
    season: str
    amount: Decimal
    quantity: Decimal
    unit: str
    period: str | None = None
    rate: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Bill:
    """A replayed billing cycle: line items and their total."""

    line_items: tuple[LineItem, ...]
    total: Decimal

    def component_total(self, component: str) -> Decimal:
        """Return the summed amount of every line for ``component``."""
        return sum(
            (line.amount for line in self.line_items if line.component == component),
            Decimal(0),
        )


def _sub_periods(
    tariff: Tariff, usage: Sequence[DailyUsage]
) -> Iterable[tuple[TariffVersion, Season, list[DailyUsage]]]:
    """Split a cycle into consecutive runs sharing one version and season."""
    for (version, season), days in groupby(
        usage,
        key=lambda du: (
            tariff.version_for(du.day),
            season_for(tariff.version_for(du.day), du.day),
        ),
    ):
        yield version, season, list(days)


def _energy_lines(
    tariff: Tariff, version: TariffVersion, season: Season, days: list[DailyUsage]
) -> list[LineItem]:
    """Price each energy component per TOU period for one sub-period."""
    kwh_by_period: dict[str, Decimal] = {}
    for day in days:
        for period, kwh in day.kwh_by_period.items():
            kwh_by_period[period] = kwh_by_period.get(period, Decimal(0)) + kwh

    return [
        LineItem(
            tariff_id=tariff.tariff_id,
            component=component.name,
            season=season.name,
            period=period,
            quantity=kwh,
            unit="kWh",
            rate=component.rate_for(season.name, period),
            amount=_to_cents(kwh * component.rate_for(season.name, period)),
        )
        for component in version.energy_components
        for period, kwh in kwh_by_period.items()
    ]


def _fixed_and_baseline_lines(
    tariff: Tariff, version: TariffVersion, season: Season, days: list[DailyUsage]
) -> list[LineItem]:
    """Compute fixed daily charges and the baseline credit for one sub-period."""
    lines = [
        LineItem(
            tariff_id=tariff.tariff_id,
            component=fixed.name,
            season=season.name,
            quantity=Decimal(len(days)),
            unit="days",
            rate=fixed.per_day,
            amount=_to_cents(fixed.per_day * len(days)),
        )
        for fixed in version.fixed_charges
    ]
    if version.baseline is not None:
        total_kwh = sum((day.total_kwh for day in days), Decimal(0))
        allowance = version.baseline.allowance_for(season.name, len(days))
        credited = min(total_kwh, allowance)
        lines.append(
            LineItem(
                tariff_id=tariff.tariff_id,
                component="baseline_credit",
                season=season.name,
                quantity=credited,
                unit="kWh",
                rate=-version.baseline.credit_per_kwh,
                amount=_to_cents(credited * -version.baseline.credit_per_kwh),
            )
        )
    return lines


def compute_bill(tariffs: Sequence[Tariff], usage: Sequence[DailyUsage]) -> Bill:
    """Replay a billing cycle's daily usage across a tariff stack.

    Mirrors utility bill arithmetic: the cycle is split into sub-periods at
    season and tariff-version boundaries; every line is rounded to cents;
    the baseline credit applies to usage up to the sub-period allowance; and
    percent surcharges compound sequentially on each sub-period's subtotal of
    rounded lines.
    """
    ordered = sorted(usage, key=lambda du: du.day)
    lines: list[LineItem] = []
    for tariff in tariffs:
        for version, season, days in _sub_periods(tariff, ordered):
            sub_lines = _fixed_and_baseline_lines(tariff, version, season, days)
            sub_lines[:0] = _energy_lines(tariff, version, season, days)
            subtotal = sum((line.amount for line in sub_lines), Decimal(0))
            for surcharge in version.percent_surcharges:
                amount = _to_cents(subtotal * surcharge.fraction)
                sub_lines.append(
                    LineItem(
                        tariff_id=tariff.tariff_id,
                        component=surcharge.name,
                        season=season.name,
                        quantity=subtotal,
                        unit="USD",
                        rate=surcharge.fraction,
                        amount=amount,
                    )
                )
                subtotal += amount
            lines.extend(sub_lines)

    return Bill(
        line_items=tuple(lines),
        total=sum((line.amount for line in lines), Decimal(0)),
    )
