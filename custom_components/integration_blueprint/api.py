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

    async def async_get_data(self) -> Any:
        """Get data from the API."""
        # Placeholder for future implementation
        return {}

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
