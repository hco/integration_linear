"""Todo list platform for integration_linear."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, CONF_TEAM_STATES, CONF_TEAMS, LOGGER
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
    # Enable support for creating, updating, and deleting todo items
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM | TodoListEntityFeature.UPDATE_TODO_ITEM
        # disabled because the UX was not as I expected
        # | TodoListEntityFeature.DELETE_TODO_ITEM
    )

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
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{team_id}"
        self._attr_name = f"Linear {team_name}"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the todo items."""
        if not self.coordinator.data:
            return []

        team_data = self.coordinator.data.get(self._team_id, {})
        todo_issues = team_data.get("todo", [])
        completed_issues = team_data.get("completed", [])

        items: list[TodoItem] = []

        # Map todo_states issues to TodoItems with NEEDS_ACTION status
        for issue in todo_issues:
            items.append(
                TodoItem(
                    uid=issue["id"],
                    summary=issue.get("title", ""),
                    status=TodoItemStatus.NEEDS_ACTION,
                )
            )

        # Map completed_state issues to TodoItems with COMPLETED status
        for issue in completed_issues:
            items.append(
                TodoItem(
                    uid=issue["id"],
                    summary=issue.get("title", ""),
                    status=TodoItemStatus.COMPLETED,
                )
            )

        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the todo list."""
        client = self.coordinator.config_entry.runtime_data.client
        team_states = self.coordinator.config_entry.data.get(CONF_TEAM_STATES, {})
        team_config = team_states.get(self._team_id, {})
        todo_states = team_config.get("todo_states", [])

        if not todo_states:
            msg = "No todo states configured for this team"
            raise ValueError(msg)

        # Use the first todo_state for new issues
        state_id = todo_states[0]

        await client.async_create_issue(
            title=item.summary or "",
            team_id=self._team_id,
            state_id=state_id,
            description=None,
        )

        # Refresh coordinator to sync UI
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(
        self, item: TodoItem, update_fields: dict[str, Any] | None = None
    ) -> None:
        """Update an item in the todo list."""
        client = self.coordinator.config_entry.runtime_data.client
        team_states = self.coordinator.config_entry.data.get(CONF_TEAM_STATES, {})
        team_config = team_states.get(self._team_id, {})
        todo_states = team_config.get("todo_states", [])
        completed_state = team_config.get("completed_state")

        issue_id = item.uid
        # Handle case where update_fields might be None or empty
        if update_fields is None:
            update_fields = {}
        new_status = update_fields.get("status")

        # If status is not in update_fields, check the item's current status
        # This handles cases where Home Assistant passes the updated item directly
        if new_status is None:
            new_status = item.status

        LOGGER.debug(
            "Updating todo item %s: new_status=%s, update_fields=%s",
            issue_id,
            new_status,
            update_fields,
        )

        if new_status == TodoItemStatus.COMPLETED:
            # Move issue to completed_state
            if not completed_state:
                error_msg = f"No completed state configured for team {self._team_name} ({self._team_id})"
                LOGGER.error(error_msg)
                raise ValueError(error_msg)
            try:
                await client.async_update_issue(issue_id, completed_state)
                LOGGER.debug("Successfully moved issue %s to completed state", issue_id)
            except Exception as e:
                LOGGER.error(
                    "Failed to update issue %s to completed state: %s", issue_id, e
                )
                raise
        elif new_status == TodoItemStatus.NEEDS_ACTION:
            # Move issue back to first todo_state
            if not todo_states:
                error_msg = f"No todo states configured for team {self._team_name} ({self._team_id})"
                LOGGER.error(error_msg)
                raise ValueError(error_msg)
            state_id = todo_states[0]
            try:
                await client.async_update_issue(issue_id, state_id)
                LOGGER.debug("Successfully moved issue %s to todo state", issue_id)
            except Exception as e:
                LOGGER.error("Failed to update issue %s to todo state: %s", issue_id, e)
                raise
        else:
            LOGGER.warning(
                "Unknown status update for issue %s: %s (update_fields: %s)",
                issue_id,
                new_status,
                update_fields,
            )

        # Refresh coordinator to sync UI
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete items from the todo list."""
        client = self.coordinator.config_entry.runtime_data.client
        team_states = self.coordinator.config_entry.data.get(CONF_TEAM_STATES, {})
        team_config = team_states.get(self._team_id, {})
        removed_state = team_config.get("removed_state")

        if not removed_state:
            msg = "No removed state configured for this team"
            raise ValueError(msg)

        # Move each issue to removed_state
        for issue_id in uids:
            await client.async_update_issue(issue_id, removed_state)

        # Refresh coordinator to sync UI
        await self.coordinator.async_request_refresh()
