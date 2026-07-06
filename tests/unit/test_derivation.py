"""Unit tests for tariff derivation (self-calibration) from hourly reads."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from custom_components.gridrate.api.derivation import HourlyRead, derive, drift_report
from custom_components.gridrate.api.tariff import load_shipped_plan

# Winter E-TOU-C delivery parameters (the shipped plan's ground truth).
PEAK_RATE = 0.39757
OFF_RATE = 0.36757
CREDIT = 0.08140
ALLOWANCE_PER_DAY = 12.9
PEAK_START, PEAK_END = 16, 21

VERSION = load_shipped_plan("pge_e_tou_c").versions[0]


def synth_reads(
    daily_kwh_plan: list[float],
    *,
    start: date = date(2027, 1, 1),
    cycle_days: int = 30,
    rate_offset: float = 0.0,
) -> list[HourlyRead]:
    """Generate opower-like hourly reads from the winter tariff.

    Mirrors how the utility bills hourly: each hour is priced at the TOU
    delivery rate, minus the baseline credit while the cycle's cumulative
    usage remains under the daily-accrued allowance.
    """
    reads: list[HourlyRead] = []
    cumulative = 0.0
    for day_index, day_kwh in enumerate(daily_kwh_plan):
        day_in_cycle = day_index % cycle_days
        if day_in_cycle == 0:
            cumulative = 0.0
        accrued_allowance = ALLOWANCE_PER_DAY * (day_in_cycle + 1)
        day = start + timedelta(days=day_index)
        # Deterministic hour-to-hour variation: identical hourly kWh would
        # give every hour the same cost-rounding bias, which real usage
        # doesn't have.
        weights = [0.5 + ((hour * 13 + day_index * 7) % 12) / 12 for hour in range(24)]
        scale = day_kwh / sum(weights)
        for hour in range(24):
            hourly_kwh = weights[hour] * scale
            in_peak = PEAK_START <= hour < PEAK_END
            rate = (PEAK_RATE if in_peak else OFF_RATE) + rate_offset
            if cumulative < accrued_allowance:
                rate -= CREDIT
            reads.append(
                HourlyRead(
                    start=datetime(day.year, day.month, day.day, hour),
                    kwh=hourly_kwh,
                    cost=round(hourly_kwh * rate, 4),
                )
            )
            cumulative += hourly_kwh
    return reads


def crossing_plan() -> list[float]:
    """60 days / 2 cycles: usage crosses the baseline late in each cycle."""
    cycle = [10.0] * 20 + [30.0] * 10
    return cycle * 2


def test_recovers_tou_window_and_rates():
    derived = derive(synth_reads(crossing_plan()))
    assert derived.peak_window == (PEAK_START, PEAK_END)
    tolerance = Decimal("0.0002")
    peak = derived.delivery_rate("peak")
    off_peak = derived.delivery_rate("off_peak")
    assert peak is not None
    assert off_peak is not None
    assert abs(peak - Decimal("0.39757")) < tolerance
    assert abs(off_peak - Decimal("0.36757")) < tolerance


def test_recovers_baseline_credit_and_allowance():
    derived = derive(synth_reads(crossing_plan()))
    assert derived.baseline_credit is not None
    assert abs(derived.baseline_credit - Decimal("0.08140")) < Decimal("0.001")
    assert derived.allowance_kwh_per_day is not None
    assert abs(derived.allowance_kwh_per_day - Decimal("12.9")) < Decimal("1.0")


def test_detects_cycle_start():
    derived = derive(synth_reads(crossing_plan()))
    # The second cycle starts 30 days in (tier falls back from 2 to 1).
    assert date(2027, 1, 31) in derived.cycle_starts


def test_no_drift_against_shipped_plan():
    derived = derive(synth_reads(crossing_plan()))
    report = drift_report(derived, VERSION, "winter")
    assert not report.has_drift, [
        (i.field, i.configured, i.derived) for i in report.drifted
    ]


def test_detects_rate_drift():
    # The utility raised rates by 2 cents; the configured tariff is stale.
    derived = derive(synth_reads(crossing_plan(), rate_offset=0.02))
    report = drift_report(derived, VERSION, "winter")
    assert report.has_drift
    drifted_fields = {item.field for item in report.drifted}
    assert "delivery_energy.peak" in drifted_fields
    assert "delivery_energy.off_peak" in drifted_fields


def test_flat_rate_has_no_peak_window():
    reads = [
        HourlyRead(
            start=datetime(2027, 1, 1 + day, hour),
            kwh=1.0,
            cost=round(1.0 * 0.30, 4),
        )
        for day in range(7)
        for hour in range(24)
    ]
    derived = derive(reads)
    assert derived.peak_window is None
    assert derived.delivery_rate("off_peak") is None or derived.period_rates


def test_empty_and_noisy_reads():
    assert derive([]).read_count == 0
    # Tiny consumption hours are excluded from derivation.
    tiny = [
        HourlyRead(start=datetime(2027, 1, 1, hour), kwh=0.01, cost=0.01)
        for hour in range(24)
    ]
    assert derive(tiny).read_count == 0
