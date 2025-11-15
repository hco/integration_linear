"""Todo list platform for integration_linear."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import TodoItem, TodoListEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_TEAMS
from .coordinator import BlueprintDataUpdateCoordinator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .data import IntegrationBlueprintConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001 Unused function argument: `hass`
    entry: IntegrationBlueprintConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the todo list platform."""
    selected_teams = entry.data.get(CONF_TEAMS, [])
    
    # Fetch team names for display
    client = entry.runtime_data.client
    try:
        all_teams = await client.async_get_teams()
        team_map = {team["id"]: team["name"] for team in all_teams}
    except Exception:  # pylint: disable=broad-except
        # If we can't fetch teams, use IDs as names
        team_map = {team_id: team_id for team_id in selected_teams}
    
    async_add_entities(
        LinearTodoListEntity(
            coordinator=entry.runtime_data.coordinator,
            team_id=team_id,
            team_name=team_map.get(team_id, team_id),
            entry_id=entry.entry_id,
        )
        for team_id in selected_teams
    )


class LinearTodoListEntity(
    CoordinatorEntity[BlueprintDataUpdateCoordinator], TodoListEntity
):
    """Linear todo list entity."""

    _attr_attribution = ATTRIBUTION

    def __init__(
        self,
        coordinator: BlueprintDataUpdateCoordinator,
        team_id: str,
        team_name: str,
        entry_id: str,
    ) -> None:
        """Initialize the todo list entity."""
        super().__init__(coordinator)
        self._team_id = team_id
        self._team_name = team_name
        self._attr_unique_id = f"{entry_id}_{team_id}"
        self._attr_name = f"Linear {team_name}"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the todo items."""
        # Empty todo list - no items yet
        return []

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the todo list."""
        # Empty todo list - no-op for now
        # Will be implemented when we add todo fetching/creation

    async def async_update_todo_item(
        self, item: TodoItem, update_fields: dict[str, Any]
    ) -> None:
        """Update an item in the todo list."""
        # Empty todo list - no-op for now
        # Will be implemented when we add todo fetching/updating

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the todo list."""
        # Empty todo list - no-op for now
        # Will be implemented when we add todo fetching/deletion

