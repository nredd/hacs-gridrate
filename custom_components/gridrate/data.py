"""Runtime data attached to each GridRate config entry.

Access pattern: ``entry.runtime_data.integration`` (coordinators are added as
the integration grows).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.loader import Integration


type GridRateConfigEntry = ConfigEntry[GridRateData]


@dataclass
class GridRateData:
    """Runtime data for a GridRate config entry.

    Stored as ``entry.runtime_data`` after a successful setup and provides typed
    access to the integration's coordinators.
    """

    integration: Integration
