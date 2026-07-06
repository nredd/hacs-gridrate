"""Realtime rate and cost coordinator.

Evaluates the configured tariff stack continuously and accrues bill-accurate
cost from a local energy meter entity:

- the marginal rate (with breakdown and hourly ``raw_today``/``raw_tomorrow``
  price curves) refreshes every minute, so TOU flips land on time;
- every meter update accrues the energy delta at the marginal rate in force,
  tier-aware against the billing cycle's baseline allowance;
- billing-cycle boundaries come straight from the utility forecast on the
  Opower coordinator (no sensor-state scraping);
- accumulators persist across restarts via a Store.

Times are Home Assistant local time, which is assumed to match the utility's
tariff timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from custom_components.gridrate.api.tariff import (
    RateBreakdown,
    Tariff,
    marginal_rate,
    period_for,
    season_for,
)
from custom_components.gridrate.const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import Event, EventStateChangedData

    from custom_components.gridrate.coordinator.opower import GridRateOpowerCoordinator
    from custom_components.gridrate.data import GridRateConfigEntry

STORE_VERSION = 1
SAVE_DELAY_SECONDS = 10
# Meter states above this are rejected as glitches (kWh in one update).
MAX_PLAUSIBLE_DELTA_KWH = 100.0


@dataclass
class RealtimeData:
    """Everything the realtime rate/cost entities render."""

    rate: RateBreakdown
    season: str
    period: str
    next_period_change: datetime
    cycle_start: date | None
    cycle_end: date | None
    cycle_kwh: float
    cycle_allowance_kwh: float | None
    baseline_remaining_kwh: float | None
    over_baseline: bool
    today_kwh: float
    today_cost: float
    cycle_cost: float
    projected_bill: float | None
    raw_today: list[dict[str, Any]]
    raw_tomorrow: list[dict[str, Any]]


class GridRateRealtimeCoordinator(DataUpdateCoordinator[RealtimeData]):
    """Compute the live marginal rate and accrue cost from a local meter."""

    config_entry: GridRateConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GridRateConfigEntry,
        tariffs: list[Tariff],
        opower_coordinator: GridRateOpowerCoordinator,
        meter_entity: str | None,
    ) -> None:
        """Initialize the realtime coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name="GridRate realtime",
            # Cheap pure-math refresh; keeps TOU flips, day rollover, and the
            # prorated fixed charge current between meter updates.
            update_interval=timedelta(minutes=1),
        )
        if not tariffs:
            msg = "Realtime coordinator requires at least one tariff"
            raise ConfigEntryError(msg)
        self.tariffs = tariffs
        self._opower = opower_coordinator
        self._meter_entity = meter_entity
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{DOMAIN}.{config_entry.entry_id}_realtime"
        )

        # Accumulators (restored from the store on setup).
        self._last_meter_value: float | None = None
        self._today: date | None = None
        self._today_kwh = 0.0
        self._today_energy_cost = 0.0
        self._cycle_start: date | None = None
        self._cycle_kwh = 0.0
        self._cycle_energy_cost = 0.0

    async def async_setup(self) -> None:
        """Restore persisted accumulators and subscribe to the meter."""
        stored = await self._store.async_load()
        if stored:
            self._last_meter_value = stored.get("last_meter_value")
            self._today = _parse_date(stored.get("today"))
            self._today_kwh = stored.get("today_kwh", 0.0)
            self._today_energy_cost = stored.get("today_energy_cost", 0.0)
            self._cycle_start = _parse_date(stored.get("cycle_start"))
            self._cycle_kwh = stored.get("cycle_kwh", 0.0)
            self._cycle_energy_cost = stored.get("cycle_energy_cost", 0.0)

        if self._meter_entity:
            self.config_entry.async_on_unload(
                async_track_state_change_event(
                    self.hass, [self._meter_entity], self._handle_meter_event
                )
            )

    # ------------------------------------------------------------------ #
    # Meter accrual
    # ------------------------------------------------------------------ #

    @callback
    def _handle_meter_event(self, event: Event[EventStateChangedData]) -> None:
        """Accrue the meter's energy delta at the marginal rate in force."""
        new_state = event.data["new_state"]
        if new_state is None:
            return
        try:
            reading = float(new_state.state)
        except TypeError, ValueError:
            return

        now = dt_util.now()
        self._roll_boundaries(now)

        previous = self._last_meter_value
        self._last_meter_value = reading
        if previous is None:
            self._schedule_save()
            return

        # A drop means the meter reset (e.g. a daily-energy sensor at
        # midnight); the new reading is the energy since the reset.
        delta = reading - previous if reading >= previous else reading
        if delta <= 0 or delta > MAX_PLAUSIBLE_DELTA_KWH:
            self._schedule_save()
            return

        rate = self._current_rate(now)
        cost = delta * float(rate.total)
        self._today_kwh += delta
        self._today_energy_cost += cost
        self._cycle_kwh += delta
        self._cycle_energy_cost += cost
        self._schedule_save()
        self.async_set_updated_data(self._build_data(now))

    def _roll_boundaries(self, now: datetime) -> None:
        """Reset the day and cycle accumulators at their boundaries."""
        today = now.date()
        if self._today != today:
            self._today = today
            self._today_kwh = 0.0
            self._today_energy_cost = 0.0

        cycle_start, _ = self._cycle_bounds()
        if cycle_start is not None and cycle_start != self._cycle_start:
            self._cycle_start = cycle_start
            self._cycle_kwh = 0.0
            self._cycle_energy_cost = 0.0

    def _schedule_save(self) -> None:
        """Persist the accumulators (debounced)."""
        self._store.async_delay_save(self._to_stored, SAVE_DELAY_SECONDS)

    def _to_stored(self) -> dict[str, Any]:
        """Serialize the accumulators for the store."""
        return {
            "last_meter_value": self._last_meter_value,
            "today": self._today.isoformat() if self._today else None,
            "today_kwh": self._today_kwh,
            "today_energy_cost": self._today_energy_cost,
            "cycle_start": self._cycle_start.isoformat() if self._cycle_start else None,
            "cycle_kwh": self._cycle_kwh,
            "cycle_energy_cost": self._cycle_energy_cost,
        }

    # ------------------------------------------------------------------ #
    # Tariff evaluation
    # ------------------------------------------------------------------ #

    def _cycle_bounds(self) -> tuple[date | None, date | None]:
        """Return the billing-cycle bounds from the utility forecast."""
        opower_data = self._opower.data or {}
        for account_data in opower_data.values():
            if account_data.forecast is not None:
                return (
                    account_data.forecast.start_date,
                    account_data.forecast.end_date,
                )
        return None, None

    def _cycle_allowance(self, start: date, end: date) -> float | None:
        """Sum the baseline allowance in kWh over ``[start, end]``."""
        total = Decimal(0)
        found = False
        for tariff in self.tariffs:
            day = start
            while day <= end:
                try:
                    version = tariff.version_for(day)
                except LookupError:
                    day += timedelta(days=1)
                    continue
                if version.baseline is None:
                    break
                season = season_for(version, day)
                total += version.baseline.allowance_for(season.name, 1)
                found = True
                day += timedelta(days=1)
        return float(total) if found else None

    def _over_baseline(self) -> tuple[float | None, bool]:
        """Return (cycle allowance, whether usage has exceeded it)."""
        start, end = self._cycle_bounds()
        if start is None or end is None:
            return None, False
        allowance = self._cycle_allowance(start, end)
        if allowance is None:
            return None, False
        return allowance, self._cycle_kwh > allowance

    def _current_rate(self, now: datetime) -> RateBreakdown:
        """Return the marginal rate breakdown in force at ``now``."""
        _, over = self._over_baseline()
        return marginal_rate(self.tariffs, now.replace(tzinfo=None), over_baseline=over)

    def _next_period_change(self, now: datetime) -> datetime:
        """Return the next instant the TOU period changes."""
        version = self.tariffs[0].version_for(now.date())
        current = period_for(version, now.replace(tzinfo=None))
        probe = now.replace(minute=0, second=0, microsecond=0)
        for _ in range(48):
            probe += timedelta(hours=1)
            try:
                probe_version = self.tariffs[0].version_for(probe.date())
            except LookupError:
                break
            if period_for(probe_version, probe.replace(tzinfo=None)) != current:
                return probe
        return probe

    def _hourly_curve(self, day: date, *, over: bool) -> list[dict[str, Any]]:
        """Render one day's hourly marginal prices (Nordpool-compatible)."""
        curve: list[dict[str, Any]] = []
        for hour in range(24):
            # Naive local time is the tariff engine's convention.
            start = datetime(day.year, day.month, day.day, hour)  # noqa: DTZ001
            try:
                rate = marginal_rate(self.tariffs, start, over_baseline=over)
            except LookupError:
                continue
            curve.append(
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(hours=1)).isoformat(),
                    "value": round(float(rate.total), 5),
                }
            )
        return curve

    def _fixed_charge_today(self, day: date) -> float:
        """Return the total fixed daily charge across the tariff stack."""
        total = Decimal(0)
        for tariff in self.tariffs:
            try:
                version = tariff.version_for(day)
            except LookupError:
                continue
            for fixed in version.fixed_charges:
                total += fixed.per_day
        return float(total)

    def _build_data(self, now: datetime) -> RealtimeData:
        """Assemble the full realtime snapshot."""
        self._roll_boundaries(now)
        allowance, over = self._over_baseline()
        rate = marginal_rate(self.tariffs, now.replace(tzinfo=None), over_baseline=over)
        cycle_start, cycle_end = self._cycle_bounds()

        fixed_daily = self._fixed_charge_today(now.date())
        day_fraction = (
            now - now.replace(hour=0, minute=0, second=0, microsecond=0)
        ).total_seconds() / 86400
        today_cost = self._today_energy_cost + fixed_daily * day_fraction

        cycle_cost = self._cycle_energy_cost
        projected: float | None = None
        if cycle_start is not None and cycle_end is not None:
            elapsed_days = (now.date() - cycle_start).days + day_fraction
            total_days = (cycle_end - cycle_start).days
            cycle_cost += fixed_daily * elapsed_days
            if elapsed_days >= 1 and total_days > 0:
                projected = cycle_cost / elapsed_days * total_days

        return RealtimeData(
            rate=rate,
            season=rate.season,
            period=rate.period,
            next_period_change=self._next_period_change(now),
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            cycle_kwh=self._cycle_kwh,
            cycle_allowance_kwh=allowance,
            baseline_remaining_kwh=(
                max(0.0, allowance - self._cycle_kwh) if allowance is not None else None
            ),
            over_baseline=over,
            today_kwh=self._today_kwh,
            today_cost=today_cost,
            cycle_cost=cycle_cost,
            projected_bill=projected,
            raw_today=self._hourly_curve(now.date(), over=over),
            raw_tomorrow=self._hourly_curve(now.date() + timedelta(days=1), over=over),
        )

    async def _async_update_data(self) -> RealtimeData:
        """Recompute the snapshot (pure math, no I/O)."""
        return self._build_data(dt_util.now())


def _parse_date(raw: str | None) -> date | None:
    """Parse an ISO date string from the store."""
    return date.fromisoformat(raw) if raw else None
