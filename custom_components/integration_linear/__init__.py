"""
Custom integration to integrate integration_linear with Home Assistant.

For more details about this integration, please refer to
https://github.com/ludeeus/integration_linear
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.const import Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_loaded_integration

from .api import (
    IntegrationBlueprintApiClient,
    IntegrationBlueprintApiClientError,
)
from .const import CONF_API_TOKEN, DOMAIN, LOGGER
from .coordinator import BlueprintDataUpdateCoordinator
from .data import IntegrationBlueprintData
from .oauth import async_get_valid_token

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

    from .data import IntegrationBlueprintConfigEntry

PLATFORMS: list[Platform] = [
    Platform.TODO,
]

# Track if service has been registered
_SERVICE_REGISTERED = False


async def _async_handle_create_issue(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle the create_issue service call."""
    team_id = call.data.get("team_id")
    team_identifier = call.data.get("team_identifier")
    title = call.data.get("title")
    assignee_email = call.data.get("assignee_email")
    label_names = call.data.get("label_names", [])
    state_name_or_id = call.data.get("state_name_or_id")
    description = call.data.get("description")
    due_date = call.data.get("due_date")

    if not title:
        msg = "title is required"
        raise ValueError(msg)

    if not team_id and not team_identifier:
        msg = "Either team_id or team_identifier is required"
        raise ValueError(msg)

    if team_id and team_identifier:
        msg = "Cannot specify both team_id and team_identifier"
        raise ValueError(msg)

    # Find the config entry for this integration
    # We'll use the first entry found, or allow specifying entry_id
    entry_id = call.data.get("entry_id")
    if entry_id:
        config_entry = hass.config_entries.async_get_entry(entry_id)
    else:
        # Find the first entry for this domain
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.runtime_data is not None
        ]
        if not entries:
            msg = f"No {DOMAIN} integration found"
            raise ValueError(msg)
        config_entry = entries[0]

    if not config_entry or not config_entry.runtime_data:
        msg = f"Config entry not found or not initialized for {DOMAIN}"
        raise ValueError(msg)

    client = config_entry.runtime_data.client
    LOGGER.info("Fetching Team ID")
    # If team_identifier is provided, look up the team
    if team_identifier:
        team = await client.async_get_team_by_identifier(team_identifier)
        if not team:
            msg = f"Team with identifier '{team_identifier}' not found"
            raise HomeAssistantError(msg)
        team_id = team["id"]

    try:
        issue = await client.async_create_issue_advanced(
            title=title,
            team_id=team_id,
            assignee_email=assignee_email,
            label_names=label_names if label_names else None,
            state_name_or_id=state_name_or_id,
            description=description,
            due_date=due_date,
        )
        LOGGER.info(
            "Created Linear issue: %s (ID: %s, URL: %s)",
            issue.get("title"),
            issue.get("id"),
            issue.get("url"),
        )
    except IntegrationBlueprintApiClientError as exception:
        # Convert to HomeAssistantError so the frontend displays
        # the message properly
        error_msg = str(exception)
        LOGGER.error("Failed to create Linear issue: %s", error_msg)
        raise HomeAssistantError(error_msg) from exception


async def async_setup(hass: HomeAssistant, config: dict) -> bool:  # noqa: ARG001
    """Set up the integration."""
    # Register the create_issue service (only once per domain)
    service_schema = vol.Schema(
        {
            vol.Exclusive("team_id", "team"): cv.string,
            vol.Exclusive("team_identifier", "team"): cv.string,
            vol.Required("title"): cv.string,
            vol.Optional("entry_id"): cv.string,
            vol.Optional("assignee_email"): cv.string,
            vol.Optional("label_names"): vol.All(cv.ensure_list, [cv.string]),
            vol.Optional("state_name_or_id"): cv.string,
            vol.Optional("description"): cv.string,
            vol.Optional("due_date"): cv.string,
        }
    )

    async def service_handler(call: ServiceCall) -> None:
        """Service handler wrapper."""
        await _async_handle_create_issue(hass, call)

    hass.services.async_register(
        DOMAIN,
        "create_issue",
        service_handler,
        schema=service_schema,
    )

    return True


# https://developers.home-assistant.io/docs/config_entries_index/#setting-up-an-entry
async def async_setup_entry(
    hass: HomeAssistant,
    entry: IntegrationBlueprintConfigEntry,
) -> bool:
    """Set up this integration using UI."""
    # Unload platforms first if they exist (for reload scenarios)
    # Only attempt to unload if the entry was previously set up
    if hasattr(entry, "runtime_data") and entry.runtime_data is not None:
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Get API token - either from OAuth or from config entry data
    api_token: str
    token_refresh_callback = None
    if CONF_API_TOKEN in entry.data:
        # API key authentication
        api_token = entry.data[CONF_API_TOKEN]
    else:
        # OAuth authentication - token is stored in entry.data
        token = entry.data.get("token", {})
        api_token = token.get("access_token", "")
        
        # Create token refresh callback for OAuth
        async def refresh_token() -> str:
            """Refresh OAuth token and return new access token."""
            return await async_get_valid_token(hass, entry)
        
        token_refresh_callback = refresh_token

    coordinator = BlueprintDataUpdateCoordinator(
        hass=hass,
        logger=LOGGER,
        name=DOMAIN,
        update_interval=timedelta(hours=1),
    )
    entry.runtime_data = IntegrationBlueprintData(
        client=IntegrationBlueprintApiClient(
            api_token=api_token,
            session=async_get_clientsession(hass),
            token_refresh_callback=token_refresh_callback,
        ),
        integration=async_get_loaded_integration(hass, entry.domain),
        coordinator=coordinator,
    )

    # https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
    await coordinator.async_config_entry_first_refresh()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: IntegrationBlueprintConfigEntry,
) -> bool:
    """Handle removal of an entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant,
    entry: IntegrationBlueprintConfigEntry,
) -> None:
    """Reload config entry when options are updated."""
    # Reload the entry to pick up new team selections
    await hass.config_entries.async_reload(entry.entry_id)
