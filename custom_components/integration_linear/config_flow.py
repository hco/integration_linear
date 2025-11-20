"""Adds config flow for Linear Integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2FlowHandler,
    LocalOAuth2ImplementationWithPkce,
)

from .api import (
    IntegrationBlueprintApiClient,
    IntegrationBlueprintApiClientAuthenticationError,
    IntegrationBlueprintApiClientCommunicationError,
    IntegrationBlueprintApiClientError,
)
from .const import CONF_API_TOKEN, CONF_TEAM_STATES, CONF_TEAMS, DOMAIN, LOGGER

if TYPE_CHECKING:
    from logging import Logger

# Hardcoded client_id for PKCE (no secret needed)
LINEAR_CLIENT_ID = "c7e22e8ffc50ea46f48e3cfb8fe40175"
LINEAR_AUTHORIZE_URL = "https://linear.app/oauth/authorize"
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"  # noqa: S105

OAUTH_SCOPES = ["write"]
class BlueprintFlowHandler(AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Config flow for Linear Integration."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._teams: list[dict[str, str]] = []
        self._api_token: str = ""
        self._selected_teams: list[str] = []
        self._team_states: dict[str, list[dict[str, Any]]] = {}
        self._current_team_index: int = 0
        self._team_states_config: dict[str, dict[str, Any]] = {}
        self._oauth_token: str | None = None
        self._oauth_data: dict[str, Any] | None = None

    @property
    def logger(self) -> Logger:
        """Return logger."""
        return LOGGER

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow handler."""
        return LinearOptionsFlowHandler(config_entry)


    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "prompt": "consent",
        }

    async def async_step_pick_implementation(
        self, user_input: dict | None = None  # noqa: ARG002
    ) -> config_entries.ConfigFlowResult:
        """Handle picking implementation - bypass and use PKCE implementation."""
        # Create our built-in OAuth implementation with PKCE
        implementation = LocalOAuth2ImplementationWithPkce(
            self.hass,
            DOMAIN,
            LINEAR_CLIENT_ID,
            authorize_url=LINEAR_AUTHORIZE_URL,
            token_url=LINEAR_TOKEN_URL,
            client_secret="",  # Empty for PKCE public client
            code_verifier_length=128,
        )

        # Store the implementation
        self.flow_impl = implementation

        # Proceed to auth step
        return await self.async_step_auth()

    async def async_step_user(
        self,
        user_input: dict | None = None,  # noqa: ARG002
    ) -> config_entries.ConfigFlowResult:
        """Handle a flow initialized by the user."""
        # Always use OAuth with our built-in PKCE implementation
        # No need to configure credentials - client_id is hardcoded
        return await self.async_step_pick_implementation()

    async def async_step_api_key(
        self,
        user_input: dict | None = None,
    ) -> config_entries.ConfigFlowResult:
        """Handle API key authentication."""
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
            step_id="api_key",
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

    async def async_oauth_create_entry(
        self, data: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Create an entry for OAuth flow."""
        # Store OAuth data for later use (preserve it through team selection)
        self._oauth_data = data.copy()

        # Get access token from OAuth data token
        token = data["token"]
        access_token = token["access_token"]

        # Validate token and fetch teams
        try:
            client = IntegrationBlueprintApiClient(
                api_token=access_token,
                session=async_create_clientsession(self.hass),
            )
            await client.async_validate_token()
            teams = await client.async_get_teams()
        except IntegrationBlueprintApiClientError as exception:
            LOGGER.exception(exception)
            return self.async_abort(reason="oauth_fetch_teams_failed")

        # Store teams temporarily and proceed to team selection
        self._teams = teams
        self._api_token = access_token
        # Proceed to team selection before creating entry
        return await self.async_step_teams()

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

    async def async_step_team_states(  # noqa: PLR0911
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
            entry_data = {
                CONF_TEAMS: self._selected_teams,
                CONF_TEAM_STATES: self._team_states_config,
            }

            # If using OAuth, merge team data with OAuth data
            if self._oauth_token and self._oauth_data:
                # OAuth flow - merge team data with stored OAuth data
                oauth_data = self._oauth_data.copy()
                oauth_data.update(entry_data)
                return self.async_create_entry(
                    title="Linear",
                    data=oauth_data,
                )

            # API key flow
            entry_data[CONF_API_TOKEN] = self._api_token
            return self.async_create_entry(
                title="Linear",
                data=entry_data,
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

        # Get API token - either from OAuth or from config entry data
        if CONF_API_TOKEN in entry.data:
            # API key authentication
            self._api_token = entry.data[CONF_API_TOKEN]
        else:
            # OAuth authentication - token is stored in entry.data
            token = entry.data.get("token", {})
            self._api_token = token.get("access_token", "")

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
            # Start with a copy of the existing entry data to preserve all other fields (including refreshed OAuth tokens)
            entry_data = dict(entry.data)
            # Update only the specific fields needed
            entry_data[CONF_TEAMS] = self._selected_teams
            entry_data[CONF_TEAM_STATES] = self._team_states_config
            # Only update API token if it's not OAuth (OAuth tokens are stored separately)
            if CONF_API_TOKEN in entry.data:
                entry_data[CONF_API_TOKEN] = self._api_token

            self.hass.config_entries.async_update_entry(entry, data=entry_data)
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
