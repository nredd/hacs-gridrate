"""Tariff drift detection.

After every utility refresh, re-derive the tariff from the fetched hourly
cost/usage reads and compare it to the configured delivery tariff. When the
utility's actual rates diverge (they changed rates and the configured tariff
is stale), raise a repair issue carrying the derived values; its fix flow
applies them as a config-entry override (see ``repairs.py``).
"""

from __future__ import annotations

from datetime import timedelta
import json
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from homeassistant.core import callback
from homeassistant.helpers import issue_registry as ir

from custom_components.gridrate.api.derivation import HourlyRead, derive, drift_report
from custom_components.gridrate.api.tariff import season_for
from custom_components.gridrate.const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.gridrate.api.tariff import Tariff
    from custom_components.gridrate.data import GridRateConfigEntry

# Require ~10 days of hourly data before trusting a drift verdict.
MIN_READS = 240

ISSUE_PREFIX = "tariff_drift"


@callback
def async_check_drift(
    hass: HomeAssistant, entry: GridRateConfigEntry, delivery: Tariff
) -> None:
    """Derive the tariff from the latest reads and raise/clear a drift issue.

    Runs as an Opower-coordinator listener after each 12h refresh. Pure math
    over the already-fetched reads — no I/O.
    """
    coordinator = entry.runtime_data.opower_coordinator
    issue_id = f"{ISSUE_PREFIX}_{entry.entry_id}"

    tz = ZoneInfo(coordinator.api.utility.timezone())
    today = None
    reads: list[HourlyRead] = []
    for account_data in (coordinator.data or {}).values():
        for cost_read in account_data.cost_reads:
            if cost_read.end_time - cost_read.start_time > timedelta(hours=1):
                continue  # only hourly-resolution reads are derivable
            local_start = cost_read.start_time.astimezone(tz).replace(tzinfo=None)
            reads.append(
                HourlyRead(
                    start=local_start,
                    kwh=cost_read.consumption,
                    cost=cost_read.provided_cost,
                )
            )
            today = max(today or local_start.date(), local_start.date())

    if today is None:
        return

    try:
        version = delivery.version_for(today)
        season = season_for(version, today)
    except LookupError:
        return

    # Restrict to the current rate regime: one version, one season.
    regime_reads = [
        read
        for read in reads
        if version.covers(read.start.date())
        and season_for(version, read.start.date()).name == season.name
    ]
    if len(regime_reads) < MIN_READS:
        LOGGER.debug(
            "Drift check skipped: %d hourly reads in current regime (< %d)",
            len(regime_reads),
            MIN_READS,
        )
        return

    derived = derive(regime_reads)
    report = drift_report(derived, version, season.name)
    if not report.has_drift:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return

    drifted = {
        item.field: {
            "configured": str(item.configured),
            "derived": str(item.derived),
        }
        for item in report.drifted
    }
    LOGGER.warning("Tariff drift detected vs %s: %s", delivery.tariff_id, drifted)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="tariff_drift",
        translation_placeholders={
            "tariff": delivery.name,
            "details": "\n".join(
                f"- `{field}`: configured {values['configured']}, "
                f"utility data says {values['derived']}"
                for field, values in drifted.items()
            ),
        },
        data={
            "entry_id": entry.entry_id,
            "season": season.name,
            "effective_on": today.isoformat(),
            # Issue data values must be scalars; the fix flow parses this.
            "fixes": json.dumps(
                {
                    item.field: str(item.derived)
                    for item in report.drifted
                    if item.derived is not None
                }
            ),
        },
    )
