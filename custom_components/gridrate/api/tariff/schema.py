"""JSON (de)serialization and validation of tariff definitions.

Pure Python (no Home Assistant imports). Tariff definitions are JSON with all
money/rate values as *strings* so they parse losslessly into
:class:`~decimal.Decimal`. Shipped plan definitions live in the adjacent
``plans/`` package directory and load via :func:`load_shipped_plan`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import resources
import json
from typing import TYPE_CHECKING, Any

from custom_components.gridrate.api.tariff.models import (
    BaselinePolicy,
    ComponentCategory,
    EnergyComponent,
    FixedCharge,
    PercentSurcharge,
    Season,
    Tariff,
    TariffVersion,
    TouWindow,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_PLANS_PACKAGE = "custom_components.gridrate.api.tariff.plans"


class TariffSchemaError(ValueError):
    """A tariff definition failed to parse or validate."""


def _decimal(raw: Any, context: str) -> Decimal:
    """Parse a JSON string into a Decimal with a helpful error."""
    if not isinstance(raw, str):
        msg = f"{context}: money values must be JSON strings, got {type(raw).__name__}"
        raise TariffSchemaError(msg)
    try:
        return Decimal(raw)
    except InvalidOperation as err:
        msg = f"{context}: {raw!r} is not a valid decimal"
        raise TariffSchemaError(msg) from err


def _month_day(raw: str, context: str) -> tuple[int, int]:
    """Parse an ``MM-DD`` string."""
    try:
        month_str, day_str = raw.split("-")
        month, day = int(month_str), int(day_str)
        # Validate via a real (leap-year) date.
        date(2000, month, day)
    except (ValueError, AttributeError) as err:
        msg = f"{context}: {raw!r} is not a valid MM-DD month-day"
        raise TariffSchemaError(msg) from err
    return month, day


def _rates(raw: Mapping[str, Any], context: str) -> dict[str, dict[str, Decimal]]:
    """Parse a ``season -> period -> rate`` table."""
    return {
        season: {
            period: _decimal(rate, f"{context}.rates[{season}][{period}]")
            for period, rate in periods.items()
        }
        for season, periods in raw.items()
    }


def _season(raw: Mapping[str, Any]) -> Season:
    """Parse one season definition."""
    name = raw["name"]
    start = _month_day(raw["from"], f"season {name!r} 'from'")
    end = _month_day(raw["to"], f"season {name!r} 'to'")
    return Season(
        name=name,
        start_month=start[0],
        start_day=start[1],
        end_month=end[0],
        end_day=end[1],
    )


def _version(raw: Mapping[str, Any], tariff_id: str) -> TariffVersion:
    """Parse one dated tariff version."""
    context = f"tariff {tariff_id!r}"
    baseline_raw = raw.get("baseline")
    baseline = (
        BaselinePolicy(
            credit_per_kwh=_decimal(
                baseline_raw["credit_per_kwh"], f"{context} baseline credit"
            ),
            allowance_kwh_per_day={
                season: _decimal(value, f"{context} baseline allowance [{season}]")
                for season, value in baseline_raw["allowance_kwh_per_day"].items()
            },
        )
        if baseline_raw is not None
        else None
    )
    effective_to = raw.get("effective_to")
    return TariffVersion(
        effective_from=date.fromisoformat(raw["effective_from"]),
        effective_to=date.fromisoformat(effective_to) if effective_to else None,
        seasons=tuple(_season(season) for season in raw.get("seasons", ())),
        tou_windows=tuple(
            TouWindow(
                period=window["period"],
                start_hour=window["start_hour"],
                end_hour=window["end_hour"],
            )
            for window in raw.get("tou_windows", ())
        ),
        default_period=raw.get("default_period", "off_peak"),
        energy_components=tuple(
            EnergyComponent(
                name=component["name"],
                category=ComponentCategory(component["category"]),
                rates=_rates(
                    component["rates"], f"{context} component {component['name']!r}"
                ),
            )
            for component in raw.get("energy_components", ())
        ),
        percent_surcharges=tuple(
            PercentSurcharge(
                name=surcharge["name"],
                percent=_decimal(
                    surcharge["percent"], f"{context} surcharge {surcharge['name']!r}"
                ),
            )
            for surcharge in raw.get("percent_surcharges", ())
        ),
        baseline=baseline,
        fixed_charges=tuple(
            FixedCharge(
                name=fixed["name"],
                per_day=_decimal(fixed["per_day"], f"{context} fixed {fixed['name']!r}"),
            )
            for fixed in raw.get("fixed_charges", ())
        ),
    )


def tariff_from_dict(raw: Mapping[str, Any]) -> Tariff:
    """Build a :class:`Tariff` from a parsed JSON mapping.

    Raises:
        TariffSchemaError: If the definition is malformed.

    """
    try:
        tariff_id = raw["id"]
        versions = tuple(_version(version, tariff_id) for version in raw["versions"])
        if not versions:
            msg = f"tariff {tariff_id!r} has no versions"
            raise TariffSchemaError(msg)
        return Tariff(
            tariff_id=tariff_id,
            name=raw["name"],
            currency=raw.get("currency", "USD"),
            versions=versions,
        )
    except KeyError as err:
        msg = f"tariff definition is missing required key {err.args[0]!r}"
        raise TariffSchemaError(msg) from err


def tariff_to_dict(tariff: Tariff) -> dict[str, Any]:
    """Serialize a :class:`Tariff` back to its JSON mapping form."""
    return {
        "id": tariff.tariff_id,
        "name": tariff.name,
        "currency": tariff.currency,
        "versions": [
            {
                "effective_from": version.effective_from.isoformat(),
                "effective_to": (
                    version.effective_to.isoformat() if version.effective_to else None
                ),
                "seasons": [
                    {
                        "name": season.name,
                        "from": f"{season.start_month:02d}-{season.start_day:02d}",
                        "to": f"{season.end_month:02d}-{season.end_day:02d}",
                    }
                    for season in version.seasons
                ],
                "tou_windows": [
                    {
                        "period": window.period,
                        "start_hour": window.start_hour,
                        "end_hour": window.end_hour,
                    }
                    for window in version.tou_windows
                ],
                "default_period": version.default_period,
                "energy_components": [
                    {
                        "name": component.name,
                        "category": component.category.value,
                        "rates": {
                            season: {
                                period: str(rate) for period, rate in periods.items()
                            }
                            for season, periods in component.rates.items()
                        },
                    }
                    for component in version.energy_components
                ],
                "percent_surcharges": [
                    {"name": surcharge.name, "percent": str(surcharge.percent)}
                    for surcharge in version.percent_surcharges
                ],
                "baseline": (
                    {
                        "credit_per_kwh": str(version.baseline.credit_per_kwh),
                        "allowance_kwh_per_day": {
                            season: str(value)
                            for season, value in version.baseline.allowance_kwh_per_day.items()
                        },
                    }
                    if version.baseline
                    else None
                ),
                "fixed_charges": [
                    {"name": fixed.name, "per_day": str(fixed.per_day)}
                    for fixed in version.fixed_charges
                ],
            }
            for version in tariff.versions
        ],
    }


def loads(text: str) -> Tariff:
    """Parse a tariff definition from a JSON string."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        msg = f"tariff definition is not valid JSON: {err}"
        raise TariffSchemaError(msg) from err
    return tariff_from_dict(raw)


def dumps(tariff: Tariff) -> str:
    """Serialize a tariff definition to a JSON string."""
    return json.dumps(tariff_to_dict(tariff), indent=2)


def shipped_plan_ids() -> list[str]:
    """List the ids of tariff definitions shipped with the integration."""
    return sorted(
        entry.name.removesuffix(".json")
        for entry in resources.files(_PLANS_PACKAGE).iterdir()
        if entry.name.endswith(".json")
    )


def load_shipped_plan(plan_id: str) -> Tariff:
    """Load a tariff definition shipped with the integration by id.

    Raises:
        TariffSchemaError: If no shipped plan has that id or it is malformed.

    """
    resource = resources.files(_PLANS_PACKAGE).joinpath(f"{plan_id}.json")
    try:
        text = resource.read_text(encoding="utf-8")
    except FileNotFoundError as err:
        msg = f"no shipped tariff plan named {plan_id!r}"
        raise TariffSchemaError(msg) from err
    return loads(text)
