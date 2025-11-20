"""Linear API Client."""

from __future__ import annotations

import socket
from typing import Any, Callable, Awaitable

import aiohttp
import async_timeout

from .const import LOGGER

LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_FORBIDDEN = 403


class IntegrationBlueprintApiClientError(Exception):
    """Exception to indicate a general API error."""


class IntegrationBlueprintApiClientCommunicationError(
    IntegrationBlueprintApiClientError,
):
    """Exception to indicate a communication error."""


class IntegrationBlueprintApiClientAuthenticationError(
    IntegrationBlueprintApiClientError,
):
    """Exception to indicate an authentication error."""


def _verify_response_or_raise(response: aiohttp.ClientResponse) -> None:
    """Verify that the response is valid."""
    if response.status in (HTTP_STATUS_UNAUTHORIZED, HTTP_STATUS_FORBIDDEN):
        msg = "Invalid API token"
        raise IntegrationBlueprintApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


def _raise_authentication_error() -> None:
    """Raise authentication error."""
    msg = "Invalid API token"
    raise IntegrationBlueprintApiClientAuthenticationError(msg)


def _raise_graphql_error(error_messages: list[str]) -> None:
    """Raise GraphQL error."""
    error_msg = f"GraphQL errors: {', '.join(error_messages)}"
    raise IntegrationBlueprintApiClientError(error_msg)


class IntegrationBlueprintApiClient:
    """Linear API Client."""

    def __init__(
        self,
        api_token: str,
        session: aiohttp.ClientSession,
        token_refresh_callback: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        """Initialize Linear API Client."""
        self._api_token = api_token
        self._session = session
        self._token_refresh_callback = token_refresh_callback
        self._refresh_in_progress = False

    async def async_validate_token(self) -> None:
        """Validate the API token by making a simple query."""
        query = "query { viewer { id } }"
        await self._graphql_query(query)

    async def async_get_teams(self) -> list[dict[str, Any]]:
        """Get all teams for the authenticated user."""
        query = "query { teams { nodes { id name key } } }"
        result = await self._graphql_query(query)
        return result.get("data", {}).get("teams", {}).get("nodes", [])

    async def async_get_team_by_identifier(
        self, identifier: str
    ) -> dict[str, Any] | None:
        """Get a team by its identifier (key/prefix)."""
        teams = await self.async_get_teams()
        for team in teams:
            if team.get("key") == identifier.upper():
                return team
        return None

    async def async_get_workflow_states(self, team_id: str) -> list[dict[str, Any]]:
        """Get workflow states for a specific team."""
        query = """
        query GetTeamStates($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                        type
                    }
                }
            }
        }
        """
        variables = {"teamId": team_id}
        result = await self._graphql_query(query, variables)
        return result.get("data", {}).get("team", {}).get("states", {}).get("nodes", [])

    async def async_get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Get a user by email address."""
        query = """
        query GetUserByEmail($email: String!) {
            users(filter: { email: { eq: $email } }) {
                nodes {
                    id
                    name
                    email
                }
            }
        }
        """
        variables = {"email": email}
        result = await self._graphql_query(query, variables)
        users = result.get("data", {}).get("users", {}).get("nodes", [])
        return users[0] if users else None

    async def async_get_labels(self, team_id: str) -> list[dict[str, Any]]:
        """Get all labels for a specific team."""
        query = """
        query GetTeamLabels($teamId: String!) {
            team(id: $teamId) {
                labels {
                    nodes {
                        id
                        name
                    }
                }
            }
        }
        """
        variables = {"teamId": team_id}
        result = await self._graphql_query(query, variables)
        return result.get("data", {}).get("team", {}).get("labels", {}).get("nodes", [])

    async def async_get_label_by_name(
        self, team_id: str, label_name: str
    ) -> dict[str, Any] | None:
        """Get a label by name for a specific team."""
        labels = await self.async_get_labels(team_id)
        for label in labels:
            if label.get("name") == label_name:
                return label
        return None

    async def async_get_state_by_name_or_id(
        self, team_id: str, state_name_or_id: str
    ) -> dict[str, Any] | None:
        """Get a workflow state by name or ID for a specific team."""
        states = await self.async_get_workflow_states(team_id)
        for state in states:
            state_id = state.get("id")
            state_name = state.get("name")
            if state_name_or_id in (state_id, state_name):
                return state
        return None

    async def async_get_data(self) -> Any:
        """Get data from the API."""
        # Placeholder for future implementation
        return {}

    async def async_get_issues(
        self,
        team_id: str,
        state_ids: list[str],
        updated_since: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get issues for a team filtered by state IDs and optionally by update date."""
        # Build filter conditionally based on whether updated_since is provided
        if updated_since:
            query = """
            query GetIssues(
                $teamId: ID!,
                $stateIds: [ID!]!,
                $updatedSince: DateTimeOrDuration!
            ) {
                issues(
                    filter: {
                        team: { id: { eq: $teamId } }
                        state: { id: { in: $stateIds } }
                        updatedAt: { gte: $updatedSince }
                    }
                ) {
                    nodes {
                        id
                        title
                        description
                        dueDate
                        state {
                            id
                            name
                        }
                        updatedAt
                        url
                    }
                }
            }
            """
            variables: dict[str, Any] = {
                "teamId": team_id,
                "stateIds": state_ids,
                "updatedSince": updated_since,
            }
        else:
            query = """
            query GetIssues($teamId: ID!, $stateIds: [ID!]!) {
                issues(
                    filter: {
                        team: { id: { eq: $teamId } }
                        state: { id: { in: $stateIds } }
                    }
                ) {
                    nodes {
                        id
                        title
                        description
                        dueDate
                        state {
                            id
                            name
                        }
                        updatedAt
                        url
                    }
                }
            }
            """
            variables: dict[str, Any] = {
                "teamId": team_id,
                "stateIds": state_ids,
            }

        result = await self._graphql_query(query, variables)
        return result.get("data", {}).get("issues", {}).get("nodes", [])

    async def async_update_issue(
        self,
        issue_id: str,
        state_id: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an issue's state, description, and/or due date.

        Args:
            issue_id: The ID of the issue to update
            state_id: The new state ID, or None to not update state
            description: The new description, or None to not update description
            due_date: The new due date (ISO 8601 format), or None to not update

        """
        # Build input object string and variable declarations with only provided fields
        input_parts: list[str] = []
        variable_declarations: list[str] = ["$issueId: String!"]
        variables: dict[str, Any] = {
            "issueId": issue_id,
        }

        if state_id is not None:
            input_parts.append("stateId: $stateId")
            variable_declarations.append("$stateId: String")
            variables["stateId"] = state_id

        # Only include description if it's not None (None means don't update)
        if description is not None:
            input_parts.append("description: $description")
            variable_declarations.append("$description: String")
            variables["description"] = description

        # Only include dueDate if it's not None (None means don't update)
        # Linear expects TimelessDate, not DateTime
        if due_date is not None:
            input_parts.append("dueDate: $dueDate")
            variable_declarations.append("$dueDate: TimelessDate")
            variables["dueDate"] = due_date

        if not input_parts:
            msg = "At least one of state_id, description, or due_date must be provided"
            raise ValueError(msg)

        input_str = ",\n                    ".join(input_parts)
        variable_decls_str = ",\n            ".join(variable_declarations)

        mutation = f"""
        mutation UpdateIssue(
            {variable_decls_str}
        ) {{
            issueUpdate(
                id: $issueId,
                input: {{
                    {input_str}
                }}
            ) {{
                success
                issue {{
                    id
                    title
                    description
                    dueDate
                    state {{
                        id
                        name
                    }}
                    updatedAt
                }}
            }}
        }}
        """

        result = await self._graphql_query(mutation, variables)
        issue_update = result.get("data", {}).get("issueUpdate", {})
        if not issue_update.get("success"):
            msg = "Failed to update issue"
            raise IntegrationBlueprintApiClientError(msg)
        return issue_update.get("issue", {})

    async def async_create_issue(
        self,
        title: str,
        team_id: str,
        state_id: str,
        description: str | None = None,
        due_date: str | None = None,
        created_by_user: str | None = None,
        created_by_user_avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new issue.

        Args:
            title: The issue title
            team_id: The team ID
            state_id: The workflow state ID
            description: Optional description
            due_date: Optional due date (ISO 8601 format)
            created_by_user: Name/identifier of the user creating the issue
            created_by_user_avatar_url: URL of the user's avatar
        """
        # Build variable declarations and input fields dynamically
        variable_declarations: list[str] = [
            "$title: String!",
            "$teamId: String!",
            "$stateId: String",
        ]
        input_fields: list[str] = [
            "title: $title",
            "teamId: $teamId",
            "stateId: $stateId",
        ]
        variables: dict[str, Any] = {
            "title": title,
            "teamId": team_id,
            "stateId": state_id,
        }

        # Add createAsUser if provided
        if created_by_user:
            variable_declarations.append("$createAsUser: String")
            input_fields.append("createAsUser: $createAsUser")
            variables["createAsUser"] = created_by_user

        if created_by_user_avatar_url:
            variable_declarations.append("$displayIconUrl: String")
            input_fields.append("displayIconUrl: $displayIconUrl")
            variables["displayIconUrl"] = created_by_user_avatar_url

        if description:
            variable_declarations.append("$description: String")
            input_fields.append("description: $description")
            variables["description"] = description

        if due_date:
            # Linear expects TimelessDate, not DateTime
            variable_declarations.append("$dueDate: TimelessDate")
            input_fields.append("dueDate: $dueDate")
            variables["dueDate"] = due_date

        variable_decls_str = ",\n            ".join(variable_declarations)
        input_fields_str = ",\n                    ".join(input_fields)

        mutation = f"""
        mutation CreateIssue(
            {variable_decls_str}
        ) {{
            issueCreate(
                input: {{
                    {input_fields_str}
                }}
            ) {{
                success
                issue {{
                    id
                    title
                    description
                    dueDate
                    state {{
                        id
                        name
                    }}
                    updatedAt
                    url
                }}
            }}
        }}
        """

        result = await self._graphql_query(mutation, variables)
        issue_create = result.get("data", {}).get("issueCreate", {})
        if not issue_create.get("success"):
            msg = "Failed to create issue"
            raise IntegrationBlueprintApiClientError(msg)
        return issue_create.get("issue", {})

    async def async_create_issue_advanced(
        self,
        title: str,
        team_id: str,
        assignee_email: str | None = None,
        label_names: list[str] | None = None,
        state_name_or_id: str | None = None,
        description: str | None = None,
        due_date: str | None = None,
        created_by_user: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new issue with advanced features.

        Args:
            title: The issue title
            team_id: The team ID
            assignee_email: Email address of the user to assign (must exist)
            label_names: List of label names to add (must exist)
            state_name_or_id: State name or ID to set
            description: Optional description
            due_date: Optional due date (ISO 8601 format)
            created_by_user: Name/identifier of the user creating the issue

        Raises:
            IntegrationBlueprintApiClientError: If user doesn't exist,
                labels don't exist, or state doesn't exist.

        """
        # Validate and get assignee if provided
        assignee_id: str | None = None
        if assignee_email:
            user = await self.async_get_user_by_email(assignee_email)
            if not user:
                msg = f"User with email {assignee_email} not found"
                raise IntegrationBlueprintApiClientError(msg)
            assignee_id = user["id"]

        # Validate and get labels if provided
        label_ids: list[str] = []
        if label_names:
            for label_name in label_names:
                label = await self.async_get_label_by_name(team_id, label_name)
                if not label:
                    msg = f"Label '{label_name}' not found for team {team_id}"
                    raise IntegrationBlueprintApiClientError(msg)
                label_ids.append(label["id"])

        # Validate and get state if provided
        state_id: str | None = None
        if state_name_or_id:
            state = await self.async_get_state_by_name_or_id(team_id, state_name_or_id)
            if not state:
                msg = f"State '{state_name_or_id}' not found for team {team_id}"
                raise IntegrationBlueprintApiClientError(msg)
            state_id = state["id"]

        # Build variable declarations and input fields dynamically
        variable_declarations: list[str] = [
            "$title: String!",
            "$teamId: String!",
        ]
        input_fields: list[str] = [
            "title: $title",
            "teamId: $teamId",
        ]
        variables: dict[str, Any] = {
            "title": title,
            "teamId": team_id,
        }

        if state_id:
            variable_declarations.append("$stateId: String")
            input_fields.append("stateId: $stateId")
            variables["stateId"] = state_id

        if assignee_id:
            variable_declarations.append("$assigneeId: String")
            input_fields.append("assigneeId: $assigneeId")
            variables["assigneeId"] = assignee_id

        if label_ids:
            variable_declarations.append("$labelIds: [String!]")
            input_fields.append("labelIds: $labelIds")
            variables["labelIds"] = label_ids

        if description:
            variable_declarations.append("$description: String")
            input_fields.append("description: $description")
            variables["description"] = description

        if due_date:
            variable_declarations.append("$dueDate: TimelessDate")
            input_fields.append("dueDate: $dueDate")
            variables["dueDate"] = due_date

        if created_by_user:
            variable_declarations.append("$createAsUser: String")
            input_fields.append("createAsUser: $createAsUser")
            variables["createAsUser"] = created_by_user

        variable_decls_str = ",\n            ".join(variable_declarations)
        input_fields_str = ",\n                    ".join(input_fields)

        mutation = f"""
        mutation CreateIssueAdvanced(
            {variable_decls_str}
        ) {{
            issueCreate(
                input: {{
                    {input_fields_str}
                }}
            ) {{
                success
                issue {{
                    id
                    title
                    description
                    dueDate
                    state {{
                        id
                        name
                    }}
                    assignee {{
                        id
                        name
                        email
                    }}
                    labels {{
                        nodes {{
                            id
                            name
                        }}
                    }}
                    updatedAt
                    url
                }}
            }}
        }}
        """

        result = await self._graphql_query(mutation, variables)
        issue_create = result.get("data", {}).get("issueCreate", {})
        if not issue_create.get("success"):
            msg = "Failed to create issue"
            raise IntegrationBlueprintApiClientError(msg)
        return issue_create.get("issue", {})

    async def _graphql_query(self, query: str, variables: dict | None = None) -> Any:
        """Execute a GraphQL query."""
        LOGGER.debug("Executing GraphQL query: %s", query)
        return await self._api_wrapper(
            method="post",
            url=LINEAR_GRAPHQL_ENDPOINT,
            data={"query": query, "variables": variables or {}},
            headers={
                "Authorization": self._api_token,
                "Content-Type": "application/json",
            },
            retry_on_auth_error=True,
        )

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
        retry_on_auth_error: bool = False,
    ) -> Any:
        """Get information from the API."""
        try:
            async with async_timeout.timeout(10):
                response = await self._session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=data,
                )

                # Read response body before checking status
                result = await response.json()
                LOGGER.debug("Response: %r", result)

                # Check for authentication errors
                is_auth_error = False
                if response.status in (HTTP_STATUS_UNAUTHORIZED, HTTP_STATUS_FORBIDDEN):
                    is_auth_error = True
                elif response.status >= HTTP_STATUS_BAD_REQUEST and "errors" in result:
                    error_messages = []
                    for err in result["errors"]:
                        message = err.get("message", "Unknown error")
                        error_messages.append(message)
                        extensions = err.get("extensions", {})
                        status_code = extensions.get("statusCode")
                        if status_code in (401, 403) or "unauthorized" in message.lower():
                            is_auth_error = True
                            break

                # Try to refresh token if we have a callback and this is an auth error
                if is_auth_error and retry_on_auth_error and self._token_refresh_callback and not self._refresh_in_progress:
                    LOGGER.info("Authentication error detected, attempting token refresh")
                    try:
                        self._refresh_in_progress = True
                        new_token = await self._token_refresh_callback()
                        self._api_token = new_token
                        # Create new headers dict with updated token
                        retry_headers = dict(headers) if headers else {}
                        retry_headers["Authorization"] = new_token
                        # Retry the request once
                        LOGGER.debug("Retrying request with refreshed token")
                        response = await self._session.request(
                            method=method,
                            url=url,
                            headers=retry_headers,
                            json=data,
                        )
                        result = await response.json()
                        LOGGER.debug("Response after retry: %r", result)
                    except Exception as refresh_exception:
                        LOGGER.error("Token refresh failed: %s", refresh_exception)
                        _raise_authentication_error()
                    finally:
                        self._refresh_in_progress = False

                # Check for HTTP errors
                if response.status in (HTTP_STATUS_UNAUTHORIZED, HTTP_STATUS_FORBIDDEN):
                    _raise_authentication_error()

                if response.status >= HTTP_STATUS_BAD_REQUEST:
                    # Check for GraphQL errors in response
                    if "errors" in result:
                        error_messages = []
                        for err in result["errors"]:
                            message = err.get("message", "Unknown error")
                            error_messages.append(message)

                            # Extract user-presentable message if available
                            extensions = err.get("extensions", {})
                            user_msg = extensions.get("userPresentableMessage")
                            if user_msg:
                                LOGGER.error(
                                    "GraphQL error user message: %s",
                                    user_msg,
                                )
                                print(f"User-presentable error message: {user_msg}")

                            # Log full error details for debugging
                            LOGGER.debug("GraphQL error details: %s", repr(err))

                        if response.status in (
                            HTTP_STATUS_UNAUTHORIZED,
                            HTTP_STATUS_FORBIDDEN,
                        ) or any(
                            "unauthorized" in msg.lower() for msg in error_messages
                        ):
                            _raise_authentication_error()
                        _raise_graphql_error(error_messages)
                    response.raise_for_status()

                # Check for GraphQL errors in successful response
                if "errors" in result:
                    error_messages = []
                    for err in result["errors"]:
                        message = err.get("message", "Unknown error")
                        error_messages.append(message)

                        # Extract user-presentable message if available
                        extensions = err.get("extensions", {})
                        user_msg = extensions.get("userPresentableMessage")
                        if user_msg:
                            LOGGER.error(
                                "GraphQL error user message: %s",
                                user_msg,
                            )
                            print(f"User-presentable error message: {user_msg}")

                        # Log full error details for debugging
                        LOGGER.debug("GraphQL error details: %s", repr(err))

                    if any(
                        "401" in msg or "403" in msg or "unauthorized" in msg.lower()
                        for msg in error_messages
                    ):
                        _raise_authentication_error()
                    _raise_graphql_error(error_messages)

                return result

        except TimeoutError as exception:
            msg = f"Timeout error fetching information - {exception}"
            raise IntegrationBlueprintApiClientCommunicationError(
                msg,
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            msg = f"Error fetching information - {exception}"
            raise IntegrationBlueprintApiClientCommunicationError(
                msg,
            ) from exception
        except IntegrationBlueprintApiClientError:
            raise
        except Exception as exception:  # pylint: disable=broad-except
            msg = f"Something really wrong happened! - {exception}"
            raise IntegrationBlueprintApiClientError(
                msg,
            ) from exception
