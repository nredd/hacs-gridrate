"""Realtime rate and cost sensors (the GridRate rate engine)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.gridrate.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date, datetime

    from homeassistant.helpers.typing import StateType

    from custom_components.gridrate.coordinator import (
        GridRateRealtimeCoordinator,
        RealtimeData,
    )
    from custom_components.gridrate.data import GridRateConfigEntry


@dataclass(frozen=True, kw_only=True)
class RealtimeEntityDescription(SensorEntityDescription):
    """Class describing realtime rate-engine sensor entities."""

    value_fn: Callable[[RealtimeData], StateType | date | datetime]
    attributes_fn: Callable[[RealtimeData], dict[str, Any]] | None = None
    requires_meter: bool = False


def _rate_attributes(data: RealtimeData) -> dict[str, Any]:
    """Attributes for the current-rate sensor: breakdown + price curves."""
    return {
        "components": {
            name: round(float(value), 5) for name, value in data.rate.components.items()
        },
        "season": data.season,
        "period": data.period,
        "tier": 2 if data.over_baseline else 1,
        "over_baseline": data.over_baseline,
        "cycle_start": data.cycle_start.isoformat() if data.cycle_start else None,
        "cycle_end": data.cycle_end.isoformat() if data.cycle_end else None,
        # Nordpool-compatible hourly price arrays for evcc/EMHASS interop.
        "raw_today": data.raw_today,
        "raw_tomorrow": data.raw_tomorrow,
    }


REALTIME_SENSORS: tuple[RealtimeEntityDescription, ...] = (
    RealtimeEntityDescription(
        key="current_rate",
        translation_key="current_rate",
        native_unit_of_measurement="USD/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=5,
        value_fn=lambda data: float(data.rate.total),
        attributes_fn=_rate_attributes,
    ),
    RealtimeEntityDescription(
        key="next_period_change",
        translation_key="next_period_change",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.next_period_change,
    ),
    RealtimeEntityDescription(
        key="billing_cycle_usage",
        translation_key="billing_cycle_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value_fn=lambda data: data.cycle_kwh,
        requires_meter=True,
    ),
    RealtimeEntityDescription(
        key="baseline_remaining",
        translation_key="baseline_remaining",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.baseline_remaining_kwh,
        requires_meter=True,
    ),
    RealtimeEntityDescription(
        key="cost_today",
        translation_key="cost_today",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.today_cost,
        requires_meter=True,
    ),
    RealtimeEntityDescription(
        key="billing_cycle_cost",
        translation_key="billing_cycle_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda data: data.cycle_cost,
        requires_meter=True,
    ),
    RealtimeEntityDescription(
        key="projected_bill",
        translation_key="projected_bill",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.projected_bill,
        requires_meter=True,
    ),
)


def rate_engine_device(entry: GridRateConfigEntry) -> DeviceInfo:
    """Return the device that groups the realtime rate-engine entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_rate_engine")},
        name="GridRate",
        manufacturer="GridRate",
        model="Rate engine",
        entry_type=DeviceEntryType.SERVICE,
    )


class RealtimeSensor(CoordinatorEntity["GridRateRealtimeCoordinator"], SensorEntity):
    """A realtime rate-engine sensor."""

    _attr_has_entity_name = True
    entity_description: RealtimeEntityDescription

    def __init__(
        self,
        coordinator: GridRateRealtimeCoordinator,
        description: RealtimeEntityDescription,
        entry: GridRateConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = rate_engine_device(entry)

    @property
    def native_value(self) -> StateType | date | datetime:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the description's extra attributes, if any."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
