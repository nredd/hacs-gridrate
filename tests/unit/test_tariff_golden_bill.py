"""Golden test: replay the May 2026 PG&E + CleanPowerSF bill.

Reproduces the real energy statement for the 05/06/2026-06/04/2026 billing
cycle (30 days, winter->summer season crossover, baseline credit hitting the
allowance cap in winter and the usage cap in summer) from the bill's own
per-day TOU usage table. The printed bill totals $158.55; the engine must
match to within a cent or two (the franchise-fee surcharge base is not fully
public and can round a cent differently).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from custom_components.gridrate.api.tariff import (
    DailyUsage,
    compute_bill,
    load_shipped_plan,
)

# (month, day, off_peak kWh, peak kWh) — transcribed from the bill's
# "Electric Usage This Period" daily table.
DAILY_USAGE = [
    (5, 6, "11.5131", "3.0576"),
    (5, 7, "9.6918", "1.9462"),
    (5, 8, "7.0347", "3.9594"),
    (5, 9, "10.3264", "6.7311"),
    (5, 10, "12.8445", "5.0408"),
    (5, 11, "15.8776", "3.8416"),
    (5, 12, "11.5446", "2.0377"),
    (5, 13, "10.6245", "2.6409"),
    (5, 14, "9.7153", "1.1096"),
    (5, 15, "9.5207", "3.1177"),
    (5, 16, "10.7915", "3.7009"),
    (5, 17, "7.2173", "3.8811"),
    (5, 18, "14.3411", "3.5327"),
    (5, 19, "13.2912", "3.3263"),
    (5, 20, "9.1433", "1.6437"),
    (5, 21, "11.8053", "3.7391"),
    (5, 22, "10.9159", "3.7557"),
    (5, 23, "13.6587", "4.5929"),
    (5, 24, "12.4268", "3.3067"),
    (5, 25, "9.8389", "5.7589"),
    (5, 26, "11.3152", "2.386"),
    (5, 27, "14.6268", "3.271"),
    (5, 28, "12.4097", "2.9898"),
    (5, 29, "11.1131", "1.9428"),
    (5, 30, "4.7922", "1.4127"),
    (5, 31, "4.3105", "1.4598"),
    (6, 1, "4.4757", "1.4296"),
    (6, 2, "4.867", "1.5661"),
    (6, 3, "4.8138", "1.3799"),
    (6, 4, "5.2479", "1.3991"),
]

USAGE = [
    DailyUsage(
        day=date(2026, month, day),
        kwh_by_period={"off_peak": Decimal(off), "peak": Decimal(peak)},
    )
    for month, day, off, peak in DAILY_USAGE
]

STACK = [load_shipped_plan("pge_e_tou_c"), load_shipped_plan("cleanpowersf_e_tou_c3")]


def test_cycle_usage_matches_bill_metering():
    total = sum(du.total_kwh for du in USAGE)
    assert total == Decimal("390.0525")
    assert len(USAGE) == 30


def test_golden_bill_total():
    bill = compute_bill(STACK, USAGE)
    # Printed bill: $115.77 delivery + $42.78 generation = $158.55.
    assert abs(bill.total - Decimal("158.55")) <= Decimal("0.02")


def test_delivery_line_items_match_bill():
    bill = compute_bill([STACK[0]], USAGE)
    assert bill.component_total("base_services_charge") == Decimal("23.80")  # 20.63+3.17
    assert bill.component_total("delivery_energy") == Decimal("147.41")
    # 33.47 + 103.17 + 3.02 + 7.75
    assert bill.component_total("baseline_credit") == Decimal("-29.35")  # -27.30-2.05
    assert bill.component_total("generation_credit") == Decimal("-41.83")  # -38.85-2.98
    assert bill.component_total("pcia") == Decimal("14.38")  # 13.45+0.93
    assert bill.component_total("sf_prop_c_tax_surcharge") == Decimal("1.13")
    # Franchise fee: printed bill says 0.23 (0.22+0.01); the surcharge base is
    # not fully public and our model rounds the summer line to 0.02.
    assert abs(
        bill.component_total("franchise_fee_surcharge") - Decimal("0.23")
    ) <= Decimal("0.01")
    assert abs(bill.total - Decimal("115.77")) <= Decimal("0.01")


def test_generation_line_items_match_bill_exactly():
    bill = compute_bill([STACK[1]], USAGE)
    by_line = {
        (line.season, line.period): line.amount
        for line in bill.line_items
        if line.component == "generation_energy"
    }
    assert by_line[("winter", "peak")] == Decimal("9.99")
    assert by_line[("winter", "off_peak")] == Decimal("29.51")
    assert by_line[("summer", "peak")] == Decimal("0.94")
    assert by_line[("summer", "off_peak")] == Decimal("2.22")
    assert bill.component_total("energy_commission_surcharge") == Decimal("0.12")
    assert bill.total == Decimal("42.78")


def test_baseline_credit_caps_at_allowance_and_usage():
    bill = compute_bill([STACK[0]], USAGE)
    credit_lines = {
        line.season: line
        for line in bill.line_items
        if line.component == "baseline_credit"
    }
    # Winter: usage (364.87 kWh) exceeds the 26-day allowance -> capped there.
    assert credit_lines["winter"].quantity == Decimal("335.40") == Decimal("12.9") * 26
    # Summer: 4-day usage (25.1791 kWh) is under the 28.4 kWh allowance.
    assert credit_lines["summer"].quantity == Decimal("25.1791")
