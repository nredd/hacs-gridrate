"""Utility-account bill sensors for GridRate.

Ported from Home Assistant core's ``opower`` integration (Apache-2.0, by
@tronikos — see NOTICE): the entity-description pattern, the ELEC/GAS bill
sensor sets, dynamic per-account devices, and stale-device cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from opower import MeterType, UnitOfMeasure

from custom_components.gridrate.const import CONF_METER_ENTITY, DOMAIN
from custom_components.gridrate.sensor.realtime import REALTIME_SENSORS, RealtimeSensor

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from custom_components.gridrate.coordinator import (
        GridRateOpowerCoordinator,
        UtilityAccountData,
    )
    from custom_components.gridrate.data import GridRateConfigEntry

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class UtilityAccountEntityDescription(SensorEntityDescription):
    """Class describing utility-account bill sensor entities."""

    value_fn: Callable[[UtilityAccountData], str | float | date | datetime | None]


COMMON_SENSORS: tuple[UtilityAccountEntityDescription, ...] = (
    UtilityAccountEntityDescription(
        key="last_changed",
        translation_key="last_changed",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_changed,
    ),
    UtilityAccountEntityDescription(
        key="last_updated",
        translation_key="last_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_updated,
    ),
)

# suggested_display_precision=0 for all sensors since Opower provides 0
# decimal points for all these. (For the statistics in the energy dashboard
# Opower does provide decimal points.)
ELEC_SENSORS: tuple[UtilityAccountEntityDescription, ...] = (
    UtilityAccountEntityDescription(
        key="elec_usage_to_date",
        translation_key="elec_usage_to_date",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        # Not TOTAL_INCREASING because it can decrease for accounts with solar
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.usage_to_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_forecasted_usage",
        translation_key="elec_forecasted_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.forecasted_usage if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_typical_usage",
        translation_key="elec_typical_usage",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.typical_usage if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_cost_to_date",
        translation_key="elec_cost_to_date",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.cost_to_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_forecasted_cost",
        translation_key="elec_forecasted_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.forecasted_cost if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_typical_cost",
        translation_key="elec_typical_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.typical_cost if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_start_date",
        translation_key="elec_start_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.forecast.start_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="elec_end_date",
        translation_key="elec_end_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.forecast.end_date if data.forecast else None,
    ),
)
GAS_SENSORS: tuple[UtilityAccountEntityDescription, ...] = (
    UtilityAccountEntityDescription(
        key="gas_usage_to_date",
        translation_key="gas_usage_to_date",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CENTUM_CUBIC_FEET,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.usage_to_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_forecasted_usage",
        translation_key="gas_forecasted_usage",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CENTUM_CUBIC_FEET,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.forecasted_usage if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_typical_usage",
        translation_key="gas_typical_usage",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CENTUM_CUBIC_FEET,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.typical_usage if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_cost_to_date",
        translation_key="gas_cost_to_date",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.cost_to_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_forecasted_cost",
        translation_key="gas_forecasted_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.forecasted_cost if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_typical_cost",
        translation_key="gas_typical_cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=0,
        value_fn=lambda data: data.forecast.typical_cost if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_start_date",
        translation_key="gas_start_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.forecast.start_date if data.forecast else None,
    ),
    UtilityAccountEntityDescription(
        key="gas_end_date",
        translation_key="gas_end_date",
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.forecast.end_date if data.forecast else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GridRateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the GridRate utility-account and realtime rate sensors."""
    coordinator = entry.runtime_data.opower_coordinator
    created_sensors: set[tuple[str, str]] = set()

    if (realtime := entry.runtime_data.realtime_coordinator) is not None:
        has_meter = bool(entry.options.get(CONF_METER_ENTITY))
        async_add_entities(
            RealtimeSensor(realtime, description, entry)
            for description in REALTIME_SENSORS
            if has_meter or not description.requires_meter
        )

    @callback
    def _update_entities() -> None:  # noqa: PLR0912 - ported nearly verbatim from core opower
        """Add entities for new accounts and clean up stale devices."""
        new_entities: list[UtilityAccountSensor] = []
        current_account_device_ids: set[str] = set()
        current_account_ids: set[str] = set()

        for account_data in coordinator.data.values():
            account = account_data.account
            forecast = account_data.forecast
            device_id = (
                f"{coordinator.api.utility.subdomain()}_{account.utility_account_id}"
            )
            current_account_device_ids.add(device_id)
            current_account_ids.add(account.utility_account_id)
            device = DeviceInfo(
                identifiers={(DOMAIN, device_id)},
                name=f"{account.meter_type.name} account {account.utility_account_id}",
                manufacturer="GridRate",
                model=coordinator.api.utility.name(),
                entry_type=DeviceEntryType.SERVICE,
            )
            sensors: tuple[UtilityAccountEntityDescription, ...] = COMMON_SENSORS
            if (
                account.meter_type is MeterType.ELEC
                and forecast is not None
                and forecast.unit_of_measure is UnitOfMeasure.KWH
            ):
                sensors += ELEC_SENSORS
            elif (
                account.meter_type is MeterType.GAS
                and forecast is not None
                and forecast.unit_of_measure in [UnitOfMeasure.THERM, UnitOfMeasure.CCF]
            ):
                sensors += GAS_SENSORS
            for sensor in sensors:
                sensor_key = (account.utility_account_id, sensor.key)
                if sensor_key in created_sensors:
                    continue
                created_sensors.add(sensor_key)
                new_entities.append(
                    UtilityAccountSensor(
                        coordinator,
                        sensor,
                        account.utility_account_id,
                        device,
                        device_id,
                    )
                )

        if new_entities:
            async_add_entities(new_entities)

        # Remove any registered devices not in the current coordinator data.
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        for device_entry in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            device_domain_ids = {
                identifier[1]
                for identifier in device_entry.identifiers
                if identifier[0] == DOMAIN
            }
            if not device_domain_ids:
                # This device has no GridRate identifiers; it may be a
                # merged/shared device owned by another integration.
                continue
            if f"{entry.entry_id}_rate_engine" in device_domain_ids:
                continue  # the realtime rate-engine device, not an account
            if not device_domain_ids.isdisjoint(current_account_device_ids):
                continue  # device is still active
            # Device is stale — remove its entities then detach it.
            for entity_entry in er.async_entries_for_device(
                entity_registry, device_entry.id, include_disabled_entities=True
            ):
                if entity_entry.config_entry_id != entry.entry_id:
                    continue
                entity_registry.async_remove(entity_entry.entity_id)
            device_registry.async_update_device(
                device_entry.id, remove_config_entry_id=entry.entry_id
            )

        # Prune sensor tracking for accounts that are no longer present.
        if created_sensors:
            stale_sensor_keys = {
                sensor_key
                for sensor_key in created_sensors
                if sensor_key[0] not in current_account_ids
            }
            created_sensors.difference_update(stale_sensor_keys)

    _update_entities()
    entry.async_on_unload(coordinator.async_add_listener(_update_entities))


class UtilityAccountSensor(CoordinatorEntity["GridRateOpowerCoordinator"], SensorEntity):
    """A bill sensor for one utility account."""

    _attr_has_entity_name = True
    entity_description: UtilityAccountEntityDescription

    def __init__(
        self,
        coordinator: GridRateOpowerCoordinator,
        description: UtilityAccountEntityDescription,
        utility_account_id: str,
        device: DeviceInfo,
        device_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"
        self._attr_device_info = device
        self.utility_account_id = utility_account_id

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.utility_account_id in self.coordinator.data

    @property
    def native_value(self) -> StateType | date | datetime:
        """Return the state."""
        return self.entity_description.value_fn(
            self.coordinator.data[self.utility_account_id]
        )
