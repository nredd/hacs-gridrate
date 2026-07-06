"""Unit tests for tariff JSON (de)serialization and validation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from custom_components.gridrate.api.tariff import (
    TariffSchemaError,
    dumps,
    load_shipped_plan,
    loads,
    shipped_plan_ids,
)


def test_shipped_plans_enumerate():
    assert shipped_plan_ids() == ["cleanpowersf_e_tou_c3", "pge_e_tou_c"]


def test_shipped_plans_load():
    pge = load_shipped_plan("pge_e_tou_c")
    assert pge.tariff_id == "pge_e_tou_c"
    version = pge.version_for(date(2026, 7, 4))
    assert version.baseline is not None
    assert version.baseline.credit_per_kwh == Decimal("0.08140")
    assert version.fixed_charges[0].per_day == Decimal("0.79343")

    cpsf = load_shipped_plan("cleanpowersf_e_tou_c3")
    assert cpsf.version_for(date(2026, 7, 4)).baseline is None


def test_unknown_shipped_plan():
    with pytest.raises(TariffSchemaError, match="no shipped tariff plan"):
        load_shipped_plan("nonexistent_plan")


def test_round_trip():
    original = load_shipped_plan("pge_e_tou_c")
    assert loads(dumps(original)) == original


def test_rates_must_be_strings():
    with pytest.raises(TariffSchemaError, match="must be JSON strings"):
        loads(
            """{"id": "x", "name": "x", "versions": [{
                "effective_from": "2026-01-01",
                "energy_components": [
                    {"name": "e", "category": "delivery", "rates": {"*": {"*": 0.5}}}
                ]}]}"""
        )


def test_invalid_decimal_rejected():
    with pytest.raises(TariffSchemaError, match="not a valid decimal"):
        loads(
            """{"id": "x", "name": "x", "versions": [{
                "effective_from": "2026-01-01",
                "energy_components": [
                    {"name": "e", "category": "delivery", "rates": {"*": {"*": "abc"}}}
                ]}]}"""
        )


def test_invalid_month_day_rejected():
    with pytest.raises(TariffSchemaError, match="MM-DD"):
        loads(
            """{"id": "x", "name": "x", "versions": [{
                "effective_from": "2026-01-01",
                "seasons": [{"name": "s", "from": "13-01", "to": "01-01"}]}]}"""
        )


def test_missing_key_rejected():
    with pytest.raises(TariffSchemaError, match="missing required key"):
        loads('{"id": "x", "versions": [{"effective_from": "2026-01-01"}]}')


def test_empty_versions_rejected():
    with pytest.raises(TariffSchemaError, match="no versions"):
        loads('{"id": "x", "name": "x", "versions": []}')


def test_invalid_json_rejected():
    with pytest.raises(TariffSchemaError, match="not valid JSON"):
        loads("{nope")
