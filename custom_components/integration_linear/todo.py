"""Todo list platform for integration_linear."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import IntegrationBlueprintApiClientError
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
    except IntegrationBlueprintApiClientError:
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
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
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

        # Map todo_states issues to TodoItems with NEEDS_ACTION status
        items: list[TodoItem] = [
            TodoItem(
                uid=issue["id"],
                summary=issue.get("title", ""),
                status=TodoItemStatus.NEEDS_ACTION,
                description=issue.get("description"),
                due=self._parse_due_date(issue.get("dueDate")),
            )
            for issue in todo_issues
        ]

        # Map completed_state issues to TodoItems with COMPLETED status
        items.extend(
            TodoItem(
                uid=issue["id"],
                summary=issue.get("title", ""),
                status=TodoItemStatus.COMPLETED,
                description=issue.get("description"),
                due=self._parse_due_date(issue.get("dueDate")),
            )
            for issue in completed_issues
        )

        return items

    @staticmethod
    def _parse_due_date(due_date_str: str | None) -> date | None:
        """
        Parse Linear's dueDate string to Home Assistant's date format.

        Linear returns ISO 8601 DateTime strings, but we only support dates.
        We extract the date portion and return it as a date object.
        """
        if not due_date_str:
            return None

        try:
            # Linear returns ISO 8601 DateTime strings, but we only need the date
            # Parse as datetime first to handle timezone info, then extract date
            normalized = due_date_str.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            # Always return just the date portion
            return parsed.date()
        except (ValueError, AttributeError):
            LOGGER.warning("Failed to parse due date: %s", due_date_str)
            return None

    @staticmethod
    def _format_due_date(due: date | datetime | None) -> str | None:
        """
        Format Home Assistant's due date to Linear's ISO 8601 date format.

        Linear expects ISO 8601 date strings (YYYY-MM-DD).
        If a datetime is provided, we extract just the date portion.
        """
        if due is None:
            return None

        # If it's a datetime, extract just the date
        if isinstance(due, datetime):
            due = due.date()

        # Format as ISO date string (YYYY-MM-DD)
        if isinstance(due, date):
            return due.isoformat()

        return None

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
            description=item.description,
            due_date=self._format_due_date(item.due),
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
        # Check if description needs to be updated before modifying update_fields
        # If update_fields is None, it means all fields are being updated
        # If "description" is in update_fields, it's explicitly being updated
        description_updated = (
            update_fields is None or "description" in (update_fields or {})
        )
        # Check if due date needs to be updated
        due_updated = update_fields is None or "due" in (update_fields or {})

        # Handle case where update_fields might be None or empty
        if update_fields is None:
            update_fields = {}
        new_status = update_fields.get("status")

        # If status is not in update_fields, check the item's current status
        # This handles cases where Home Assistant passes the updated item directly
        if new_status is None:
            new_status = item.status

        LOGGER.debug(
            "Updating todo item %s: new_status=%s, update_fields=%s, "
            "description_updated=%s, due_updated=%s",
            issue_id,
            new_status,
            update_fields,
            description_updated,
            due_updated,
        )

        # Determine if we need to update status
        # Only COMPLETED and NEEDS_ACTION are handled
        status_changed = new_status in (
            TodoItemStatus.COMPLETED,
            TodoItemStatus.NEEDS_ACTION,
        )

        if new_status is not None and not status_changed:
            LOGGER.warning(
                "Unknown status update for issue %s: %s (update_fields: %s)",
                issue_id,
                new_status,
                update_fields,
            )

        # Check if we need to update any fields (description, due, or status)
        fields_updated = description_updated or due_updated
        # If both description/due and status need updating, do it in one call
        if fields_updated and status_changed:
            if new_status == TodoItemStatus.COMPLETED:
                if not completed_state:
                    error_msg = (
                        f"No completed state configured for team {self._team_name} "
                        f"({self._team_id})"
                    )
                    LOGGER.error(error_msg)
                    raise ValueError(error_msg)
                try:
                    await client.async_update_issue(
                        issue_id=issue_id,
                        state_id=completed_state,
                        description=item.description if description_updated else None,
                        due_date=(
                            self._format_due_date(item.due) if due_updated else None
                        ),
                    )
                    LOGGER.debug(
                        "Successfully moved issue %s to completed state "
                        "with field updates",
                        issue_id,
                    )
                except Exception as e:
                    LOGGER.error(
                        "Failed to update issue %s to completed state: %s", issue_id, e
                    )
                    raise
            elif new_status == TodoItemStatus.NEEDS_ACTION:
                if not todo_states:
                    error_msg = (
                        f"No todo states configured for team {self._team_name} "
                        f"({self._team_id})"
                    )
                    LOGGER.error(error_msg)
                    raise ValueError(error_msg)
                state_id = todo_states[0]
                try:
                    await client.async_update_issue(
                        issue_id=issue_id,
                        state_id=state_id,
                        description=item.description if description_updated else None,
                        due_date=(
                            self._format_due_date(item.due) if due_updated else None
                        ),
                    )
                    LOGGER.debug(
                        "Successfully moved issue %s to todo state "
                        "with field updates",
                        issue_id,
                    )
                except Exception as e:
                    LOGGER.error(
                        "Failed to update issue %s to todo state: %s", issue_id, e
                    )
                    raise
        else:
            # Update description/due and status separately
            if fields_updated:
                await client.async_update_issue(
                    issue_id=issue_id,
                    state_id=None,
                    description=item.description if description_updated else None,
                    due_date=(
                        self._format_due_date(item.due) if due_updated else None
                    ),
                )

            if status_changed:
                if new_status == TodoItemStatus.COMPLETED:
                    # Move issue to completed_state
                    if not completed_state:
                        error_msg = (
                            f"No completed state configured for team {self._team_name} "
                            f"({self._team_id})"
                        )
                        LOGGER.error(error_msg)
                        raise ValueError(error_msg)
                    try:
                        await client.async_update_issue(
                            issue_id=issue_id,
                            state_id=completed_state,
                        )
                        LOGGER.debug(
                            "Successfully moved issue %s to completed state",
                            issue_id,
                        )
                    except Exception as e:
                        LOGGER.error(
                            "Failed to update issue %s to completed state: %s",
                            issue_id,
                            e,
                        )
                        raise
                elif new_status == TodoItemStatus.NEEDS_ACTION:
                    # Move issue back to first todo_state
                    if not todo_states:
                        error_msg = (
                            f"No todo states configured for team {self._team_name} "
                            f"({self._team_id})"
                        )
                        LOGGER.error(error_msg)
                        raise ValueError(error_msg)
                    state_id = todo_states[0]
                    try:
                        await client.async_update_issue(
                            issue_id=issue_id,
                            state_id=state_id,
                        )
                        LOGGER.debug(
                            "Successfully moved issue %s to todo state", issue_id
                        )
                    except Exception as e:
                        LOGGER.error(
                            "Failed to update issue %s to todo state: %s", issue_id, e
                        )
                        raise

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
            await client.async_update_issue(
                issue_id=issue_id,
                state_id=removed_state,
            )

        # Refresh coordinator to sync UI
        await self.coordinator.async_request_refresh()
