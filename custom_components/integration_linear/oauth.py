"""OAuth2 token refresh helper for Linear Integration."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2ImplementationWithPkce,
)

from .config_flow import LINEAR_AUTHORIZE_URL, LINEAR_CLIENT_ID, LINEAR_TOKEN_URL
from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_get_valid_token(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> str:
    """
    Get a valid access token, refreshing if necessary.

    Args:
        hass: Home Assistant instance
        entry: Config entry containing OAuth token

    Returns:
        Valid access token

    Raises:
        ValueError: If entry doesn't use OAuth or token refresh fails

    """
    # Check if this entry uses OAuth (has token in data, not CONF_API_TOKEN)
    if "token" not in entry.data:
        msg = "Entry does not use OAuth authentication"
        raise ValueError(msg)

    token = entry.data["token"]
    access_token = token.get("access_token", "")

    # Check if token is expired or about to expire (within 60 seconds)
    expires_at = token.get("expires_at", 0)
    if expires_at and time.time() >= (expires_at - 60):
        # Token is expired or about to expire, refresh it
        LOGGER.debug("Token expired or about to expire, refreshing")
        token = await async_refresh_token(hass, entry)

    return token.get("access_token", access_token)


async def async_refresh_token(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """
    Refresh the OAuth token and update the config entry.

    Args:
        hass: Home Assistant instance
        entry: Config entry containing OAuth token

    Returns:
        Updated token data

    Raises:
        ValueError: If entry doesn't use OAuth or token refresh fails

    """
    # Check if this entry uses OAuth (has token in data, not CONF_API_TOKEN)
    if "token" not in entry.data:
        msg = "Entry does not use OAuth authentication"
        raise ValueError(msg)

    # Get current token
    current_token = entry.data["token"]

    # Create the OAuth2 implementation (same as in config flow)
    # This is a local implementation, so we recreate it
    implementation = LocalOAuth2ImplementationWithPkce(
        hass,
        DOMAIN,
        LINEAR_CLIENT_ID,
        authorize_url=LINEAR_AUTHORIZE_URL,
        token_url=LINEAR_TOKEN_URL,
        client_secret="",  # Empty for PKCE public client
        code_verifier_length=128,
    )

    # Refresh the token using the implementation
    try:
        new_token = await implementation.async_refresh_token(current_token)
    except Exception as exception:
        LOGGER.error("Failed to refresh OAuth token: %s", exception)
        error_msg = f"Token refresh failed: {exception}"
        raise ValueError(error_msg) from exception
    else:
        # Update the config entry with the new token
        entry_data = dict(entry.data)
        entry_data["token"] = new_token
        hass.config_entries.async_update_entry(entry, data=entry_data)

        LOGGER.debug("OAuth token refreshed successfully")
        return new_token

