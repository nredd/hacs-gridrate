"""Constants for the GridRate integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "gridrate"
ATTRIBUTION = "Data provided by the utility via Opower"

# Entities are updated from shared coordinators; serialize platform updates.
PARALLEL_UPDATES = 0
