"""Constants for integration_linear."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "integration_linear"
ATTRIBUTION = "Data provided by Linear"

CONF_API_TOKEN = "api_token"
CONF_TEAMS = "teams"
CONF_TEAM_STATES = "team_states"

COMPLETED_LOOKBACK_DAYS = 7
