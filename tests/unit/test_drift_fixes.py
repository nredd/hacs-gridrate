"""Unit tests for applying drift fixes to a tariff definition."""

from __future__ import annotations

from datetime import date

from custom_components.gridrate.api.derivation import apply_drift_fixes
from custom_components.gridrate.api.tariff import (
    load_shipped_plan,
    tariff_from_dict,
    tariff_to_dict,
)

EFFECTIVE = date(2026, 7, 4)


def test_apply_drift_fixes_patches_delivery_and_baseline():
    original = tariff_to_dict(load_shipped_plan("pge_e_tou_c"))
    patched = apply_drift_fixes(
        original,
        "summer",
        EFFECTIVE,
        {
            "delivery_energy.peak": "0.54240",
            "delivery_energy.off_peak": "0.41940",
            "baseline_credit": "0.09000",
            "baseline_allowance_kwh_per_day": "7.5",
        },
    )
    # The original mapping is untouched.
    assert original != patched

    tariff = tariff_from_dict(patched)
    version = tariff.version_for(EFFECTIVE)
    delivery = version.energy_components[0]
    assert str(delivery.rate_for("summer", "peak")) == "0.54240"
    assert str(delivery.rate_for("summer", "off_peak")) == "0.41940"
    # Winter rates are untouched.
    assert str(delivery.rate_for("winter", "peak")) == "0.39757"
    assert version.baseline is not None
    assert str(version.baseline.credit_per_kwh) == "0.09000"
    assert str(version.baseline.allowance_kwh_per_day["summer"]) == "7.5"
    assert str(version.baseline.allowance_kwh_per_day["winter"]) == "12.9"


def test_apply_drift_fixes_ignores_uncovered_date():
    original = tariff_to_dict(load_shipped_plan("pge_e_tou_c"))
    patched = apply_drift_fixes(
        original, "summer", date(2020, 1, 1), {"delivery_energy.peak": "9.99"}
    )
    assert patched == original
