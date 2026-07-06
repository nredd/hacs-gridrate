"""Realtime rate-engine binary sensors for GridRate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.gridrate.const import CONF_METER_ENTITY
from custom_components.gridrate.sensor.realtime import rate_engine_device

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from custom_components.gridrate.coordinator import (
        GridRateRealtimeCoordinator,
        RealtimeData,
    )
    from custom_components.gridrate.data import GridRateConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RealtimeBinaryEntityDescription(BinarySensorEntityDescription):
    """Class describing realtime rate-engine binary sensor entities."""

    value_fn: Callable[[RealtimeData], bool]
    requires_meter: bool = False


BINARY_SENSORS: tuple[RealtimeBinaryEntityDescription, ...] = (
    RealtimeBinaryEntityDescription(
        key="peak_period",
        translation_key="peak_period",
        value_fn=lambda data: data.period == "peak",
    ),
    RealtimeBinaryEntityDescription(
        key="over_baseline",
        translation_key="over_baseline",
        value_fn=lambda data: data.over_baseline,
        requires_meter=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 - platform setup signature
    entry: GridRateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the GridRate realtime binary sensors."""
    if (realtime := entry.runtime_data.realtime_coordinator) is None:
        return
    has_meter = bool(entry.options.get(CONF_METER_ENTITY))
    async_add_entities(
        RealtimeBinarySensor(realtime, description, entry)
        for description in BINARY_SENSORS
        if has_meter or not description.requires_meter
    )


class RealtimeBinarySensor(
    CoordinatorEntity["GridRateRealtimeCoordinator"], BinarySensorEntity
):
    """A realtime rate-engine binary sensor."""

    _attr_has_entity_name = True
    entity_description: RealtimeBinaryEntityDescription

    def __init__(
        self,
        coordinator: GridRateRealtimeCoordinator,
        description: RealtimeBinaryEntityDescription,
        entry: GridRateConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = rate_engine_device(entry)

    @property
    def is_on(self) -> bool:
        """Return the binary state."""
        return self.entity_description.value_fn(self.coordinator.data)
