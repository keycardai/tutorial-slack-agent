"""Google REST API Client.

Provides async HTTP client for making authenticated requests to Google APIs.
Token is provided by the calling tool function from Keycard AccessContext.
"""

from typing import Any

import httpx

GOOGLE_API_URL = "https://www.googleapis.com"
GOOGLE_DOCS_API_URL = "https://docs.googleapis.com"
GOOGLE_GMAIL_API_URL = "https://gmail.googleapis.com"
GOOGLE_SHEETS_API_URL = "https://sheets.googleapis.com"


class GoogleClientError(Exception):
    """Raised when Google API returns an error."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def request(
    method: str,
    path: str,
    *,
    token: str,
    base_url: str = GOOGLE_API_URL,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    raw_response: bool = False,
) -> dict[str, Any] | str | list:
    """Make an authenticated request to Google API.

    Args:
        method: HTTP method (GET, POST, PATCH, PUT, DELETE).
        path: API path (e.g., "/calendar/v3/users/me/calendarList").
        token: Google API access token (required).
        base_url: Base URL for the API (default: googleapis.com).
        params: Optional query parameters.
        json: Optional JSON body for POST/PATCH/PUT.
        raw_response: If True, return response text instead of JSON
            (used for Drive file content downloads).

    Returns:
        Parsed JSON response (dict or list), raw string if raw_response=True,
        or empty dict for 204 responses.

    Raises:
        GoogleClientError: If the API returns an error.
    """
    headers = {
        "Authorization": f"Bearer {token}",
    }

    url = f"{base_url}{path}"

    # Filter out None values from params
    if params:
        params = {k: v for k, v in params.items() if v is not None}

    # Filter out None values from json body
    if json:
        json = {k: v for k, v in json.items() if v is not None}

    async with httpx.AsyncClient() as client:
        response = await client.request(
            method,
            url,
            headers=headers,
            params=params,
            json=json,
            timeout=30.0,
        )

        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_obj = error_data.get("error", {})
                if isinstance(error_obj, dict):
                    message = error_obj.get("message", response.text)
                else:
                    message = response.text
            except Exception:
                message = response.text
            raise GoogleClientError(
                f"Google API error ({response.status_code}): {message}",
                status_code=response.status_code,
            )

        # Handle raw response (for file content downloads)
        if raw_response:
            return response.text

        # Handle empty responses
        if response.status_code == 204 or not response.content:
            return {}

        return response.json()
