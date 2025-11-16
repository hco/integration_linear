"""DataUpdateCoordinator for integration_linear."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    IntegrationBlueprintApiClientAuthenticationError,
    IntegrationBlueprintApiClientError,
)
from .const import COMPLETED_LOOKBACK_DAYS, CONF_TEAMS, CONF_TEAM_STATES, LOGGER

if TYPE_CHECKING:
    from .data import IntegrationBlueprintConfigEntry


# https://developers.home-assistant.io/docs/integration_fetching_data#coordinated-single-api-poll-for-data-for-all-entities
class BlueprintDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    config_entry: IntegrationBlueprintConfigEntry

    async def _async_update_data(self) -> Any:
        """Update data via library."""
        try:
            client = self.config_entry.runtime_data.client
            teams = self.config_entry.data.get(CONF_TEAMS, [])
            team_states = self.config_entry.data.get(CONF_TEAM_STATES, {})
            
            result: dict[str, dict[str, list[dict[str, Any]]]] = {}
            
            # Calculate cutoff date for completed issues (7 days ago)
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=COMPLETED_LOOKBACK_DAYS)
            updated_since = cutoff_date.isoformat()
            
            for team_id in teams:
                team_config = team_states.get(team_id, {})
                todo_states = team_config.get("todo_states", [])
                completed_state = team_config.get("completed_state")
                
                team_data: dict[str, list[dict[str, Any]]] = {
                    "todo": [],
                    "completed": [],
                }
                
                # Fetch issues in todo_states (no date filter)
                if todo_states:
                    try:
                        todo_issues = await client.async_get_issues(
                            team_id=team_id,
                            state_ids=todo_states,
                        )
                        team_data["todo"] = todo_issues
                    except IntegrationBlueprintApiClientError as exception:
                        LOGGER.warning(
                            "Failed to fetch todo issues for team %s: %s",
                            team_id,
                            exception,
                        )
                
                # Fetch issues in completed_state (filter: updated in last 7 days)
                if completed_state:
                    try:
                        completed_issues = await client.async_get_issues(
                            team_id=team_id,
                            state_ids=[completed_state],
                            updated_since=updated_since,
                        )
                        team_data["completed"] = completed_issues
                    except IntegrationBlueprintApiClientError as exception:
                        LOGGER.warning(
                            "Failed to fetch completed issues for team %s: %s",
                            team_id,
                            exception,
                        )
                
                result[team_id] = team_data
            
            return result
        except IntegrationBlueprintApiClientAuthenticationError as exception:
            raise ConfigEntryAuthFailed(exception) from exception
        except IntegrationBlueprintApiClientError as exception:
            raise UpdateFailed(exception) from exception
