"""Linear API Client."""

from __future__ import annotations

import socket
from typing import Any

import aiohttp
import async_timeout

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
    ) -> None:
        """Initialize Linear API Client."""
        self._api_token = api_token
        self._session = session

    async def async_validate_token(self) -> None:
        """Validate the API token by making a simple query."""
        query = "query { viewer { id } }"
        await self._graphql_query(query)

    async def async_get_teams(self) -> list[dict[str, str]]:
        """Get all teams for the authenticated user."""
        query = "query { teams { nodes { id name } } }"
        result = await self._graphql_query(query)
        return result.get("data", {}).get("teams", {}).get("nodes", [])

    async def async_get_workflow_states(self, team_id: str) -> list[dict[str, Any]]:
        """Get workflow states for a specific team."""
        query = """
        query GetTeamStates($teamId: ID!) {
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
    ) -> dict[str, Any]:
        """Create a new issue."""
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

    async def _graphql_query(self, query: str, variables: dict | None = None) -> Any:
        """Execute a GraphQL query."""
        return await self._api_wrapper(
            method="post",
            url=LINEAR_GRAPHQL_ENDPOINT,
            data={"query": query, "variables": variables or {}},
            headers={
                "Authorization": self._api_token,
                "Content-Type": "application/json",
            },
        )

    async def _api_wrapper(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        headers: dict | None = None,
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

                # Check for HTTP errors
                if response.status in (HTTP_STATUS_UNAUTHORIZED, HTTP_STATUS_FORBIDDEN):
                    _raise_authentication_error()

                if response.status >= HTTP_STATUS_BAD_REQUEST:
                    # Check for GraphQL errors in response
                    if "errors" in result:
                        error_messages = [
                            err.get("message", "Unknown error")
                            for err in result["errors"]
                        ]
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
                    error_messages = [
                        err.get("message", "Unknown error") for err in result["errors"]
                    ]
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
