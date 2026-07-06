"""Unit tests for tariff evaluation: seasons, TOU windows, marginal rates."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from custom_components.gridrate.api.tariff import (
    DailyUsage,
    compute_bill,
    load_shipped_plan,
    marginal_rate,
    period_for,
    season_for,
)

PGE = load_shipped_plan("pge_e_tou_c")
CPSF = load_shipped_plan("cleanpowersf_e_tou_c3")
STACK = [PGE, CPSF]
VERSION = PGE.versions[0]


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 5, 31), "winter"),
        (date(2026, 6, 1), "summer"),
        (date(2026, 9, 30), "summer"),
        (date(2026, 10, 1), "winter"),
        (date(2027, 1, 15), "winter"),  # winter wraps the year end
    ],
)
def test_season_boundaries(day, expected):
    assert season_for(VERSION, day).name == expected


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (15, 59, "off_peak"),
        (16, 0, "peak"),
        (20, 59, "peak"),
        (21, 0, "off_peak"),
        (0, 0, "off_peak"),
    ],
)
def test_tou_boundaries(hour, minute, expected):
    when = datetime(2026, 7, 4, hour, minute)
    assert period_for(VERSION, when) == expected


def test_version_selection_by_date():
    assert VERSION.covers(date(2026, 3, 1))
    assert not VERSION.covers(date(2026, 2, 28))
    with pytest.raises(LookupError):
        PGE.version_for(date(2026, 2, 28))


def test_marginal_rate_summer_offpeak_tier1():
    rate = marginal_rate(STACK, datetime(2026, 7, 4, 10, 0))
    assert rate.season == "summer"
    assert rate.period == "off_peak"
    assert not rate.over_baseline
    assert rate.components["delivery_energy"] == Decimal("0.39940")
    assert rate.components["generation_energy"] == Decimal("0.11447")
    assert rate.components["baseline_credit"] == Decimal("-0.08140")
    # Full marginal rate ~= $0.3555/kWh (plan table: ~0.3557).
    assert Decimal("0.35") < rate.total < Decimal("0.36")


def test_marginal_rate_summer_peak_tier2():
    rate = marginal_rate(STACK, datetime(2026, 7, 4, 17, 0), over_baseline=True)
    assert rate.period == "peak"
    assert "baseline_credit" not in rate.components
    # Full marginal rate ~= $0.61/kWh (plan table: ~0.6084).
    assert Decimal("0.60") < rate.total < Decimal("0.62")


def test_marginal_rate_winter_vs_summer_delivery():
    winter = marginal_rate(STACK, datetime(2027, 1, 10, 17, 0))
    summer = marginal_rate(STACK, datetime(2026, 7, 10, 17, 0))
    assert winter.components["delivery_energy"] == Decimal("0.39757")
    assert summer.components["delivery_energy"] == Decimal("0.52240")
    assert summer.total > winter.total


def test_percent_surcharges_compound_on_marginal_rate():
    rate = marginal_rate([PGE], datetime(2026, 7, 4, 10, 0))
    base = (
        rate.components["delivery_energy"]
        + rate.components["generation_credit"]
        + rate.components["pcia"]
        + rate.components["baseline_credit"]
    )
    franchise = base * Decimal("0.0021")
    prop_c = (base + franchise) * Decimal("0.00985")
    assert rate.components["franchise_fee_surcharge"] == franchise
    assert rate.components["sf_prop_c_tax_surcharge"] == prop_c
    assert rate.total == base + franchise + prop_c


def test_compute_bill_splits_at_season_boundary():
    usage = [
        DailyUsage(day=date(2026, 5, 31), kwh_by_period={"off_peak": Decimal(10)}),
        DailyUsage(day=date(2026, 6, 1), kwh_by_period={"off_peak": Decimal(10)}),
    ]
    bill = compute_bill([PGE], usage)
    seasons = {
        line.season for line in bill.line_items if line.component == "delivery_energy"
    }
    assert seasons == {"winter", "summer"}


def test_compute_bill_orders_unsorted_usage():
    usage = [
        DailyUsage(day=date(2026, 6, 1), kwh_by_period={"off_peak": Decimal(10)}),
        DailyUsage(day=date(2026, 5, 31), kwh_by_period={"off_peak": Decimal(10)}),
    ]
    assert compute_bill([PGE], usage).total == compute_bill([PGE], usage[::-1]).total
