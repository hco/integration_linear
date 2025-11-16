"""Adds config flow for Linear Integration."""

from __future__ import annotations

from typing import Any

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
from .const import CONF_API_TOKEN, CONF_TEAM_STATES, CONF_TEAMS, DOMAIN, LOGGER


class BlueprintFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Linear Integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._teams: list[dict[str, str]] = []
        self._api_token: str = ""
        self._selected_teams: list[str] = []
        self._team_states: dict[str, list[dict[str, Any]]] = {}
        self._current_team_index: int = 0
        self._team_states_config: dict[str, dict[str, Any]] = {}

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
                # Store selected teams and proceed to state configuration
                self._selected_teams = selected_teams
                return await self.async_step_team_states()

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

    async def async_step_team_states(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle team state configuration step - processes one team at a time."""
        _errors = {}
        client = IntegrationBlueprintApiClient(
            api_token=self._api_token,
            session=async_create_clientsession(self.hass),
        )

        # Initialize if starting fresh
        if self._current_team_index == 0:
            self._team_states_config = {}

        # Fetch workflow states for current team if not already fetched
        current_team_id = self._selected_teams[self._current_team_index]
        if current_team_id not in self._team_states:
            try:
                states = await client.async_get_workflow_states(current_team_id)
                self._team_states[current_team_id] = states
            except IntegrationBlueprintApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "fetch_states_failed"
                return self.async_show_form(
                    step_id="team_states",
                    data_schema=vol.Schema({}),
                    errors=_errors,
                )

        if user_input is not None:
            # Validate state configuration for current team
            todo_states = user_input.get("todo_states", [])
            completed_state = user_input.get("completed_state")
            removed_state = user_input.get("removed_state")

            # Validate all three fields are provided
            if not todo_states:
                _errors["todo_states"] = "required"
            if not completed_state:
                _errors["completed_state"] = "required"
            if not removed_state:
                _errors["removed_state"] = "required"

            if _errors:
                # Rebuild form with errors
                return await self._build_team_states_form(_errors)

            # Store configuration for current team
            self._team_states_config[current_team_id] = {
                "todo_states": todo_states,
                "completed_state": completed_state,
                "removed_state": removed_state,
            }

            # Move to next team
            self._current_team_index += 1

            # If more teams to configure, fetch states for next team and show form
            if self._current_team_index < len(self._selected_teams):
                next_team_id = self._selected_teams[self._current_team_index]
                # Fetch states for next team if not already fetched
                if next_team_id not in self._team_states:
                    try:
                        states = await client.async_get_workflow_states(next_team_id)
                        self._team_states[next_team_id] = states
                    except IntegrationBlueprintApiClientError as exception:
                        LOGGER.exception(exception)
                        _errors["base"] = "fetch_states_failed"
                        return await self._build_team_states_form(_errors)
                return await self._build_team_states_form({})

            # All teams configured, create config entry
            return self.async_create_entry(
                title="Linear",
                data={
                    CONF_API_TOKEN: self._api_token,
                    CONF_TEAMS: self._selected_teams,
                    CONF_TEAM_STATES: self._team_states_config,
                },
            )

        # Build initial form for current team
        return await self._build_team_states_form(_errors)

    def _find_default_states(
        self,
        states: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Find default states based on common names."""
        defaults = {}

        for state in states:
            state_name = state.get("name", "").lower()
            state_id = state["id"]

            # Match "Done" for completed state
            if state_name == "done" and "completed_state" not in defaults:
                defaults["completed_state"] = state_id

            # Match "Cancelled" or "Canceled" for removed state
            if (
                state_name in ["cancelled", "canceled"]
                and "removed_state" not in defaults
            ):
                defaults["removed_state"] = state_id

            # Match "Todo" or "To Do" for todo states
            if state_name in ["todo", "to do"] and "todo_states" not in defaults:
                defaults["todo_states"] = [state_id]

        return defaults

    async def _build_team_states_form(
        self,
        errors: dict[str, str],
    ) -> config_entries.ConfigFlowResult:
        """Build the team states configuration form for the current team."""
        current_team_id = self._selected_teams[self._current_team_index]
        team_map = {team["id"]: team["name"] for team in self._teams}
        current_team_name = team_map.get(current_team_id, current_team_id)
        states = self._team_states.get(current_team_id, [])

        # Build state options
        state_options = [
            selector.SelectOptionDict(value=state["id"], label=state["name"])
            for state in states
        ]

        # Get existing configuration if editing
        existing_config = self._team_states_config.get(current_team_id, {})

        # If no existing configuration, try to find defaults
        if not existing_config:
            existing_config = self._find_default_states(states)

        # Use static keys that can be translated
        schema_dict = {
            vol.Required(
                "todo_states",
                default=existing_config.get("todo_states", []),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=True,
                ),
            ),
            vol.Required(
                "completed_state",
                default=existing_config.get("completed_state"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=False,
                ),
            ),
            vol.Required(
                "removed_state",
                default=existing_config.get("removed_state"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=False,
                ),
            ),
        }

        return self.async_show_form(
            step_id="team_states",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"team_name": current_team_name},
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
        self.config_entry = config_entry
        self._teams: list[dict[str, str]] = []
        self._api_token: str = ""
        self._selected_teams: list[str] = []
        self._team_states: dict[str, list[dict[str, Any]]] = {}
        self._current_team_index: int = 0
        self._team_states_config: dict[str, dict[str, Any]] = {}

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
                # Store selected teams and proceed to state configuration
                self._selected_teams = selected_teams
                return await self.async_step_options_team_states()

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

    async def async_step_options_team_states(
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle options flow - processes one team at a time."""
        _errors = {}
        entry = self.config_entry
        client = IntegrationBlueprintApiClient(
            api_token=self._api_token,
            session=async_create_clientsession(self.hass),
        )

        # Initialize if starting fresh
        if self._current_team_index == 0:
            # Load existing configuration
            existing_states = entry.data.get(CONF_TEAM_STATES, {})
            self._team_states_config = existing_states.copy()

        # Fetch workflow states for current team if not already fetched
        current_team_id = self._selected_teams[self._current_team_index]
        if current_team_id not in self._team_states:
            try:
                states = await client.async_get_workflow_states(current_team_id)
                self._team_states[current_team_id] = states
            except IntegrationBlueprintApiClientError as exception:
                LOGGER.exception(exception)
                _errors["base"] = "fetch_states_failed"
                return self.async_show_form(
                    step_id="options_team_states",
                    data_schema=vol.Schema({}),
                    errors=_errors,
                )

        if user_input is not None:
            # Validate state configuration for current team
            todo_states = user_input.get("todo_states", [])
            completed_state = user_input.get("completed_state")
            removed_state = user_input.get("removed_state")

            # Validate all three fields are provided
            if not todo_states:
                _errors["todo_states"] = "required"
            if not completed_state:
                _errors["completed_state"] = "required"
            if not removed_state:
                _errors["removed_state"] = "required"

            if _errors:
                # Rebuild form with errors
                return await self._build_options_team_states_form(_errors)

            # Store configuration for current team
            self._team_states_config[current_team_id] = {
                "todo_states": todo_states,
                "completed_state": completed_state,
                "removed_state": removed_state,
            }

            # Move to next team
            self._current_team_index += 1

            # If more teams to configure, fetch states for next team and show form
            if self._current_team_index < len(self._selected_teams):
                next_team_id = self._selected_teams[self._current_team_index]
                # Fetch states for next team if not already fetched
                if next_team_id not in self._team_states:
                    try:
                        states = await client.async_get_workflow_states(next_team_id)
                        self._team_states[next_team_id] = states
                    except IntegrationBlueprintApiClientError as exception:
                        LOGGER.exception(exception)
                        _errors["base"] = "fetch_states_failed"
                        return await self._build_options_team_states_form(_errors)
                return await self._build_options_team_states_form({})

            # All teams configured, update config entry
            self.hass.config_entries.async_update_entry(
                entry,
                data={
                    CONF_API_TOKEN: self._api_token,
                    CONF_TEAMS: self._selected_teams,
                    CONF_TEAM_STATES: self._team_states_config,
                },
            )
            return self.async_create_entry(data={})

        # Build initial form for current team
        return await self._build_options_team_states_form(_errors)

    def _find_default_states(
        self,
        states: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Find default states based on common names."""
        defaults = {}

        for state in states:
            state_name = state.get("name", "").lower()
            state_id = state["id"]

            # Match "Done" for completed state
            if state_name == "done" and "completed_state" not in defaults:
                defaults["completed_state"] = state_id

            # Match "Cancelled" or "Canceled" for removed state
            if (
                state_name in ["cancelled", "canceled"]
                and "removed_state" not in defaults
            ):
                defaults["removed_state"] = state_id

            # Match "Todo" or "To Do" for todo states
            if state_name in ["todo", "to do"] and "todo_states" not in defaults:
                defaults["todo_states"] = [state_id]

        return defaults

    async def _build_options_team_states_form(
        self,
        errors: dict[str, str],
    ) -> config_entries.ConfigFlowResult:
        """Build the options team states configuration form for the current team."""
        current_team_id = self._selected_teams[self._current_team_index]
        team_map = {team["id"]: team["name"] for team in self._teams}
        current_team_name = team_map.get(current_team_id, current_team_id)
        states = self._team_states.get(current_team_id, [])

        # Build state options
        state_options = [
            selector.SelectOptionDict(value=state["id"], label=state["name"])
            for state in states
        ]

        # Get existing configuration for current team
        existing_config = self._team_states_config.get(current_team_id, {})

        # If no existing configuration, try to find defaults
        if not existing_config:
            existing_config = self._find_default_states(states)

        # Use static keys that can be translated
        schema_dict = {
            vol.Required(
                "todo_states",
                default=existing_config.get("todo_states", []),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=True,
                ),
            ),
            vol.Required(
                "completed_state",
                default=existing_config.get("completed_state"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=False,
                ),
            ),
            vol.Required(
                "removed_state",
                default=existing_config.get("removed_state"),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_options,
                    multiple=False,
                ),
            ),
        }

        return self.async_show_form(
            step_id="options_team_states",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"team_name": current_team_name},
        )
