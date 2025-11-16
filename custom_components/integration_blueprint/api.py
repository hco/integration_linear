"""Linear API Client."""

from __future__ import annotations

import socket
from typing import Any

import aiohttp
import async_timeout

LINEAR_GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"


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
    if response.status in (401, 403):
        msg = "Invalid API token"
        raise IntegrationBlueprintApiClientAuthenticationError(
            msg,
        )
    response.raise_for_status()


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
            query GetIssues($teamId: ID!, $stateIds: [ID!]!, $updatedSince: DateTimeOrDuration!) {
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
        state_id: str,
    ) -> dict[str, Any]:
        """Update an issue's state."""
        mutation = """
        mutation UpdateIssue($issueId: String!, $stateId: String) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) {
                success
                issue {
                    id
                    title
                    state {
                        id
                        name
                    }
                    updatedAt
                }
            }
        }
        """
        variables = {
            "issueId": issue_id,
            "stateId": state_id,
        }
        result = await self._graphql_query(mutation, variables)
        issue_update = result.get("data", {}).get("issueUpdate", {})
        if not issue_update.get("success"):
            raise IntegrationBlueprintApiClientError("Failed to update issue")
        return issue_update.get("issue", {})

    async def async_create_issue(
        self,
        title: str,
        team_id: str,
        state_id: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new issue."""
        mutation = """
        mutation CreateIssue($title: String!, $teamId: String!, $stateId: String, $description: String) {
            issueCreate(
                input: {
                    title: $title
                    teamId: $teamId
                    stateId: $stateId
                    description: $description
                }
            ) {
                success
                issue {
                    id
                    title
                    description
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
            "title": title,
            "teamId": team_id,
            "stateId": state_id,
        }
        if description:
            variables["description"] = description

        result = await self._graphql_query(mutation, variables)
        issue_create = result.get("data", {}).get("issueCreate", {})
        if not issue_create.get("success"):
            raise IntegrationBlueprintApiClientError("Failed to create issue")
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
                if response.status in (401, 403):
                    msg = "Invalid API token"
                    raise IntegrationBlueprintApiClientAuthenticationError(msg)
                
                if response.status >= 400:
                    # Check for GraphQL errors in response
                    if "errors" in result:
                        error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
                        if response.status in (401, 403) or any("unauthorized" in msg.lower() for msg in error_messages):
                            raise IntegrationBlueprintApiClientAuthenticationError(
                                "Invalid API token"
                            )
                        raise IntegrationBlueprintApiClientError(
                            f"GraphQL errors: {', '.join(error_messages)}"
                        )
                    response.raise_for_status()
                
                # Check for GraphQL errors in successful response
                if "errors" in result:
                    error_messages = [err.get("message", "Unknown error") for err in result["errors"]]
                    if any("401" in msg or "403" in msg or "unauthorized" in msg.lower() for msg in error_messages):
                        raise IntegrationBlueprintApiClientAuthenticationError(
                            "Invalid API token"
                        )
                    raise IntegrationBlueprintApiClientError(
                        f"GraphQL errors: {', '.join(error_messages)}"
                    )
                
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
