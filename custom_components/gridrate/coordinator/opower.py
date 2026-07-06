"""Coordinator handling utility-account (Opower) connections.

Ported from Home Assistant core's ``opower`` integration (Apache-2.0, by
@tronikos — see NOTICE), with these adaptations:

- external statistics are written under the ``gridrate:`` prefix;
- the legacy statistics-format migration was dropped (fresh domain);
- the fetched cost reads are retained on each account's data as the feed for
  tariff derivation and the realtime cost coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter
from opower import (
    Account,
    AggregateType,
    CostRead,
    Forecast,
    MeterType,
    Opower,
    ReadResolution,
    create_cookie_jar,
)
from opower.exceptions import ApiException, CannotConnect, InvalidAuth, MfaChallenge

from custom_components.gridrate.const import (
    CONF_LOGIN_DATA,
    CONF_TOTP_SECRET,
    CONF_UTILITY,
    DOMAIN,
    LOGGER,
)

if TYPE_CHECKING:
    from custom_components.gridrate.data import GridRateConfigEntry


@dataclass
class UtilityAccountData:
    """Per-utility-account data exposed by the coordinator."""

    account: Account
    forecast: Forecast | None
    last_changed: datetime | None
    last_updated: datetime
    cost_reads: list[CostRead]
    """Multi-resolution cost/usage reads from the latest refresh (hourly for
    the recent window). Feed for tariff derivation and realtime costing."""


class GridRateOpowerCoordinator(DataUpdateCoordinator[dict[str, UtilityAccountData]]):
    """Fetch utility data, update sensors, and insert statistics."""

    config_entry: GridRateConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GridRateConfigEntry,
    ) -> None:
        """Initialize the data handler."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="GridRate utility account",
            # Data is updated daily on Opower.
            # Refresh every 12h to be at most 12h behind.
            update_interval=timedelta(hours=12),
        )
        self.api = Opower(
            async_create_clientsession(hass, cookie_jar=create_cookie_jar()),
            config_entry.data[CONF_UTILITY],
            config_entry.data[CONF_USERNAME],
            config_entry.data[CONF_PASSWORD],
            config_entry.data.get(CONF_TOTP_SECRET),
            config_entry.data.get(CONF_LOGIN_DATA),
        )

        @callback
        def _dummy_listener() -> None:
            pass

        # Force the coordinator to periodically update by registering at least
        # one listener. Needed when _async_update_data returns {} for utilities
        # that don't provide a forecast, which results in no sensors added, no
        # registered listeners, and thus no periodic _insert_statistics calls.
        self.async_add_listener(_dummy_listener)

    async def _async_update_data(self) -> dict[str, UtilityAccountData]:
        """Fetch data from the API endpoint."""
        try:
            # Login expires after a few minutes. Given the infrequent updating
            # (every 12h) assume the previous session has expired and re-login.
            await self.api.async_login()
        except (InvalidAuth, MfaChallenge) as err:
            LOGGER.error("Error during login: %s", err)
            raise ConfigEntryAuthFailed from err
        except CannotConnect as err:
            LOGGER.error("Error during login: %s", err)
            msg = f"Error during login: {err}"
            raise UpdateFailed(msg) from err

        try:
            accounts = await self.api.async_get_accounts()
        except ApiException:
            LOGGER.exception("Error getting accounts")
            raise

        try:
            forecasts_list = await self.api.async_get_forecast()
        except ApiException:
            LOGGER.exception("Error getting forecasts")
            raise

        forecasts = {f.account.utility_account_id: f for f in forecasts_list}
        LOGGER.debug("Updating sensor data with: %s", forecasts)

        # Because Opower provides historical usage/cost with a delay of a
        # couple of days we need to insert data into statistics.
        results = await self._insert_statistics(accounts)
        return {
            account.utility_account_id: UtilityAccountData(
                account=account,
                forecast=forecasts.get(account.utility_account_id),
                last_changed=results.get(account.utility_account_id, (None, []))[0],
                last_updated=dt_util.utcnow(),
                cost_reads=results.get(account.utility_account_id, (None, []))[1],
            )
            for account in accounts
        }

    async def _insert_statistics(  # noqa: PLR0915 - ported nearly verbatim from core opower
        self, accounts: list[Account]
    ) -> dict[str, tuple[datetime | None, list[CostRead]]]:
        """Insert cost/consumption statistics under the ``gridrate:`` prefix."""
        results: dict[str, tuple[datetime | None, list[CostRead]]] = {}
        for account in accounts:
            id_prefix = (
                (
                    f"{self.api.utility.subdomain()}_{account.meter_type.name}_"
                    f"{account.utility_account_id}"
                )
                # Some utilities like AEP have "-" in their account id.
                # Other utilities like ngny-gas have "-" in their subdomain.
                # Replace it with "_" to avoid "Invalid statistic_id".
                .replace("-", "_")
                .lower()
            )
            cost_statistic_id = f"{DOMAIN}:{id_prefix}_energy_cost"
            compensation_statistic_id = f"{DOMAIN}:{id_prefix}_energy_compensation"
            consumption_statistic_id = f"{DOMAIN}:{id_prefix}_energy_consumption"
            return_statistic_id = f"{DOMAIN}:{id_prefix}_energy_return"
            LOGGER.debug(
                "Updating Statistics for %s, %s, %s, and %s",
                cost_statistic_id,
                compensation_statistic_id,
                consumption_statistic_id,
                return_statistic_id,
            )

            name_prefix = (
                f"GridRate {self.api.utility.subdomain()} "
                f"{account.meter_type.name.lower()} {account.utility_account_id}"
            )
            cost_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name_prefix} cost",
                source=DOMAIN,
                statistic_id=cost_statistic_id,
                unit_class=None,
                unit_of_measurement=None,
            )
            compensation_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name_prefix} compensation",
                source=DOMAIN,
                statistic_id=compensation_statistic_id,
                unit_class=None,
                unit_of_measurement=None,
            )
            consumption_unit_class = (
                EnergyConverter.UNIT_CLASS
                if account.meter_type is MeterType.ELEC
                else VolumeConverter.UNIT_CLASS
            )
            consumption_unit = (
                UnitOfEnergy.KILO_WATT_HOUR
                if account.meter_type is MeterType.ELEC
                else UnitOfVolume.CENTUM_CUBIC_FEET
            )
            consumption_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name_prefix} consumption",
                source=DOMAIN,
                statistic_id=consumption_statistic_id,
                unit_class=consumption_unit_class,
                unit_of_measurement=consumption_unit,
            )
            return_metadata = StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"{name_prefix} return",
                source=DOMAIN,
                statistic_id=return_statistic_id,
                unit_class=consumption_unit_class,
                unit_of_measurement=consumption_unit,
            )

            last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, consumption_statistic_id, True, set()
            )
            if not last_stat:
                LOGGER.debug("Updating statistic for the first time")
                cost_reads = await self._async_get_cost_reads(
                    account, self.api.utility.timezone()
                )
                cost_sum = 0.0
                compensation_sum = 0.0
                consumption_sum = 0.0
                return_sum = 0.0
                last_stats_time = None
            else:
                cost_reads = await self._async_get_cost_reads(
                    account,
                    self.api.utility.timezone(),
                    last_stat[consumption_statistic_id][0]["start"],
                )
                if not cost_reads:
                    LOGGER.debug("No recent usage/cost data. Skipping update")
                    continue
                start = cost_reads[0].start_time
                LOGGER.debug("Getting statistics at: %s", start)
                # In the common case there should be a previous statistic at
                # start time so we only need to fetch one statistic. If there
                # isn't any, fetch all.
                stats = {}
                for end in (start + timedelta(seconds=1), None):
                    stats = await get_instance(self.hass).async_add_executor_job(
                        statistics_during_period,
                        self.hass,
                        start,
                        end,
                        {
                            cost_statistic_id,
                            compensation_statistic_id,
                            consumption_statistic_id,
                            return_statistic_id,
                        },
                        "hour",
                        None,
                        {"sum"},
                    )
                    if stats:
                        break
                    if end:
                        LOGGER.debug(
                            "Not found. Trying to find the oldest statistic after %s",
                            start,
                        )
                if not stats:
                    # get_last_statistics found a stat so statistics_during_period
                    # should also have found at least one.
                    msg = f"Statistics missing for {consumption_statistic_id}"
                    raise UpdateFailed(msg)

                def _safe_get_sum(records: list[Any]) -> float:
                    if records and "sum" in records[0]:
                        return float(records[0]["sum"])
                    return 0.0

                cost_sum = _safe_get_sum(stats.get(cost_statistic_id, []))
                compensation_sum = _safe_get_sum(stats.get(compensation_statistic_id, []))
                consumption_sum = _safe_get_sum(stats.get(consumption_statistic_id, []))
                return_sum = _safe_get_sum(stats.get(return_statistic_id, []))
                last_stats_time = stats[consumption_statistic_id][0]["start"]

            last_changed: datetime | None = None
            if cost_reads:
                last_changed = cost_reads[-1].start_time
            elif last_stats_time is not None:
                last_changed = dt_util.utc_from_timestamp(last_stats_time)
            results[account.utility_account_id] = (last_changed, cost_reads)

            cost_statistics = []
            compensation_statistics = []
            consumption_statistics = []
            return_statistics = []

            for cost_read in cost_reads:
                start = cost_read.start_time
                if last_stats_time is not None and start.timestamp() <= last_stats_time:
                    continue

                cost_state = max(0, cost_read.provided_cost)
                compensation_state = max(0, -cost_read.provided_cost)
                consumption_state = max(0, cost_read.consumption)
                return_state = max(0, -cost_read.consumption)

                cost_sum += cost_state
                compensation_sum += compensation_state
                consumption_sum += consumption_state
                return_sum += return_state

                cost_statistics.append(
                    StatisticData(start=start, state=cost_state, sum=cost_sum)
                )
                compensation_statistics.append(
                    StatisticData(
                        start=start, state=compensation_state, sum=compensation_sum
                    )
                )
                consumption_statistics.append(
                    StatisticData(
                        start=start, state=consumption_state, sum=consumption_sum
                    )
                )
                return_statistics.append(
                    StatisticData(start=start, state=return_state, sum=return_sum)
                )

            LOGGER.debug(
                "Adding %s statistics for %s", len(cost_statistics), cost_statistic_id
            )
            async_add_external_statistics(self.hass, cost_metadata, cost_statistics)
            LOGGER.debug(
                "Adding %s statistics for %s",
                len(compensation_statistics),
                compensation_statistic_id,
            )
            async_add_external_statistics(
                self.hass, compensation_metadata, compensation_statistics
            )
            LOGGER.debug(
                "Adding %s statistics for %s",
                len(consumption_statistics),
                consumption_statistic_id,
            )
            async_add_external_statistics(
                self.hass, consumption_metadata, consumption_statistics
            )
            LOGGER.debug(
                "Adding %s statistics for %s",
                len(return_statistics),
                return_statistic_id,
            )
            async_add_external_statistics(self.hass, return_metadata, return_statistics)

        return results

    async def _async_get_cost_reads(  # noqa: PLR0912, PLR0915 - ported nearly verbatim from core opower
        self, account: Account, time_zone_str: str, start_time: float | None = None
    ) -> list[CostRead]:
        """Get cost reads.

        If start_time is None, get cost reads since account activation,
        otherwise since start_time - 30 days to allow corrections in data from
        utilities.

        We read at different resolutions depending on age:
        - month resolution for all years (since account activation)
        - day resolution for past 3 years (if the read resolution supports it)
        - hour resolution for past 2 months (if the read resolution supports it)
        """

        def _update_with_finer_cost_reads(
            cost_reads: list[CostRead], finer_cost_reads: list[CostRead]
        ) -> None:
            for i, cost_read in enumerate(cost_reads):
                for j, finer_cost_read in enumerate(finer_cost_reads):
                    if cost_read.start_time == finer_cost_read.start_time:
                        cost_reads[i:] = finer_cost_reads[j:]
                        return
                    if cost_read.end_time == finer_cost_read.start_time:
                        cost_reads[i + 1 :] = finer_cost_reads[j:]
                        return
                    if cost_read.end_time < finer_cost_read.start_time:
                        break
            cost_reads += finer_cost_reads

        tz = await dt_util.async_get_time_zone(time_zone_str)
        if start_time is None:
            start = None
        else:
            start = datetime.fromtimestamp(start_time, tz=tz) - timedelta(days=30)
        end = dt_util.now(tz)
        LOGGER.debug("Getting monthly cost reads: %s - %s", start, end)
        try:
            cost_reads = await self.api.async_get_cost_reads(
                account, AggregateType.BILL, start, end
            )
        except ApiException:
            LOGGER.exception("Error getting monthly cost reads")
            raise
        LOGGER.debug("Got %s monthly cost reads", len(cost_reads))
        if account.read_resolution is ReadResolution.BILLING:
            return cost_reads

        if start_time is None:
            start = end - timedelta(days=3 * 365)
        else:
            if cost_reads:
                start = cost_reads[0].start_time
            if start is None:
                msg = "Cost reads unexpectedly missing a start time"
                raise UpdateFailed(msg)
            start = max(start, end - timedelta(days=3 * 365))
        LOGGER.debug("Getting daily cost reads: %s - %s", start, end)
        try:
            daily_cost_reads = await self.api.async_get_cost_reads(
                account, AggregateType.DAY, start, end
            )
        except ApiException:
            LOGGER.exception("Error getting daily cost reads")
            raise
        LOGGER.debug("Got %s daily cost reads", len(daily_cost_reads))
        _update_with_finer_cost_reads(cost_reads, daily_cost_reads)
        if account.read_resolution is ReadResolution.DAY:
            return cost_reads

        if start_time is None:
            start = end - timedelta(days=2 * 30)
        else:
            if start is None:
                msg = "Cost reads unexpectedly missing a start time"
                raise UpdateFailed(msg)
            start = max(start, end - timedelta(days=2 * 30))
        LOGGER.debug("Getting hourly cost reads: %s - %s", start, end)
        try:
            hourly_cost_reads = await self.api.async_get_cost_reads(
                account, AggregateType.HOUR, start, end
            )
        except ApiException:
            LOGGER.exception("Error getting hourly cost reads")
            raise
        LOGGER.debug("Got %s hourly cost reads", len(hourly_cost_reads))
        _update_with_finer_cost_reads(cost_reads, hourly_cost_reads)
        LOGGER.debug("Got %s cost reads", len(cost_reads))
        return cost_reads
