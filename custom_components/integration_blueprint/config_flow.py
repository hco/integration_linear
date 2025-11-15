"""Adds config flow for Linear Integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    IntegrationBlueprintApiClient,
    IntegrationBlueprintApiClientAuthenticationError,
    IntegrationBlueprintApiClientCommunicationError,
    IntegrationBlueprintApiClientError,
)
from .const import CONF_API_TOKEN, CONF_TEAMS, DOMAIN, LOGGER


class BlueprintFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Linear Integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._teams: list[dict[str, str]] = []
        self._api_token: str = ""

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return LinearOptionsFlowHandler(config_entry)

    async def async_step_user(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        _errors = {}
        if user_input is not None:
            try:
                await self._test_token(api_token=user_input[CONF_API_TOKEN])
            except IntegrationBlueprintApiClientAuthenticationError as exception:
                LOGGER.warning(exception)
                _errors["base"] = "auth"
            except IntegrationBlueprintApiClientCommunicationError as exception:
                LOGGER.error(exception)
                _errors["base"] = "connection"
            except IntegrationBlueprintApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "unknown"
            else:
                # Store token temporarily and proceed to team selection
                self._api_token = user_input[CONF_API_TOKEN]
                return await self.async_step_teams()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_TOKEN): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def async_step_teams(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle team selection step."""
        _errors = {}
        
        # Fetch teams if not already fetched
        if not self._teams:
            try:
                client = IntegrationBlueprintApiClient(
                    api_token=self._api_token,
                    session=async_create_clientsession(self.hass),
                )
                self._teams = await client.async_get_teams()
            except IntegrationBlueprintApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "fetch_teams_failed"
                return self.async_show_form(
                    step_id="teams",
                    data_schema=vol.Schema({}),
                    errors=_errors,
                )

        if user_input is not None:
            selected_teams = user_input.get(CONF_TEAMS, [])
            if not selected_teams:
                _errors["base"] = "no_teams_selected"
            else:
                # Create config entry
                return self.async_create_entry(
                    title="Linear",
                    data={
                        CONF_API_TOKEN: self._api_token,
                        CONF_TEAMS: selected_teams,
                    },
                )

        # Build options for team selector
        team_options = [
            selector.SelectOptionDict(value=team["id"], label=team["name"])
            for team in self._teams
        ]

        return self.async_show_form(
            step_id="teams",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEAMS): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=team_options,
                            multiple=True,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )

    async def _test_token(self, api_token: str) -> None:
        """Validate API token."""
        client = IntegrationBlueprintApiClient(
            api_token=api_token,
            session=async_create_clientsession(self.hass),
        )
        await client.async_validate_token()


class LinearOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow handler for Linear Integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._teams: list[dict[str, str]] = []
        self._api_token: str = ""

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow initialization."""
        return await self.async_step_options_teams(user_input)

    async def async_step_options_teams(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow for team selection."""
        _errors = {}
        entry = self.config_entry
        
        # Use existing token
        self._api_token = entry.data.get(CONF_API_TOKEN, "")

        # Fetch teams if not already fetched
        if not self._teams:
            try:
                client = IntegrationBlueprintApiClient(
                    api_token=self._api_token,
                    session=async_create_clientsession(self.hass),
                )
                self._teams = await client.async_get_teams()
            except IntegrationBlueprintApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "fetch_teams_failed"
                return self.async_show_form(
                    step_id="options_teams",
                    data_schema=vol.Schema({}),
                    errors=_errors,
                )

        if user_input is not None:
            selected_teams = user_input.get(CONF_TEAMS, [])
            if not selected_teams:
                _errors["base"] = "no_teams_selected"
            else:
                # Update config entry data directly
                # This will trigger the update listener which reloads the entry
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        CONF_API_TOKEN: self._api_token,
                        CONF_TEAMS: selected_teams,
                    },
                )
                # Return success - the update listener will handle reload
                return self.async_create_entry(data={})

        # Build options for team selector
        team_options = [
            selector.SelectOptionDict(value=team["id"], label=team["name"])
            for team in self._teams
        ]
        
        # Pre-select currently selected teams
        current_teams = entry.data.get(CONF_TEAMS, [])

        return self.async_show_form(
            step_id="options_teams",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TEAMS,
                        default=current_teams,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=team_options,
                            multiple=True,
                        ),
                    ),
                },
            ),
            errors=_errors,
        )
