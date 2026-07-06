"""Generic utility rate engine: models, evaluation, and JSON schema.

Pure Python — nothing in this package imports Home Assistant.
"""

from __future__ import annotations

from custom_components.gridrate.api.tariff.engine import (
    Bill,
    DailyUsage,
    LineItem,
    RateBreakdown,
    compute_bill,
    marginal_rate,
    period_for,
    season_for,
)
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
from custom_components.gridrate.api.tariff.schema import (
    TariffSchemaError,
    dumps,
    load_shipped_plan,
    loads,
    shipped_plan_ids,
    tariff_from_dict,
    tariff_to_dict,
)

__all__ = [
    "BaselinePolicy",
    "Bill",
    "ComponentCategory",
    "DailyUsage",
    "EnergyComponent",
    "FixedCharge",
    "LineItem",
    "PercentSurcharge",
    "RateBreakdown",
    "Season",
    "Tariff",
    "TariffSchemaError",
    "TariffVersion",
    "TouWindow",
    "compute_bill",
    "dumps",
    "load_shipped_plan",
    "loads",
    "marginal_rate",
    "period_for",
    "season_for",
    "shipped_plan_ids",
    "tariff_from_dict",
    "tariff_to_dict",
]
