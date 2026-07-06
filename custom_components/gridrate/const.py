"""Constants for the GridRate integration."""

from __future__ import annotations

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "gridrate"
ATTRIBUTION = "Data provided by the utility via Opower"

# Config entry data keys (utility account, ported from core opower).
CONF_UTILITY = "utility"
CONF_TOTP_SECRET = "totp_secret"  # noqa: S105 - config key name, not a secret
CONF_LOGIN_DATA = "login_data"

# Options keys (rate engine).
CONF_METER_ENTITY = "meter_entity"
CONF_DELIVERY_PLAN = "delivery_plan"
CONF_GENERATION_PLAN = "generation_plan"
# JSON-mapping tariff override written by the drift repair fix flow.
CONF_DELIVERY_OVERRIDE = "delivery_override"

# Option value meaning "no plan selected".
PLAN_NONE = "none"

# Entities are updated from shared coordinators; serialize platform updates.
PARALLEL_UPDATES = 0
