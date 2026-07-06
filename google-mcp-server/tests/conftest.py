"""Pytest configuration and fixtures for Google MCP Server tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP


@pytest.fixture
def mock_access_ctx():
    """Create a mock AccessContext that returns a valid token."""
    access_ctx = MagicMock()
    access_ctx.has_errors.return_value = False

    token_result = MagicMock()
    token_result.access_token = "test-google-token"
    access_ctx.access.return_value = token_result

    return access_ctx


@pytest.fixture
def mock_context(mock_access_ctx):
    """Create a mock MCP Context with Keycard state."""
    ctx = MagicMock()
    ctx.get_state.return_value = mock_access_ctx
    return ctx


@pytest.fixture
def mcp_server():
    """Create a test FastMCP server instance."""
    mcp = FastMCP("Test Google MCP Server")
    return mcp


@pytest.fixture
def mock_google_request():
    """Fixture to mock Google API requests."""
    with patch("google_mcp_server.client.request", new_callable=AsyncMock) as mock:
        yield mock
