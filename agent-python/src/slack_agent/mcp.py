"""keycardai-mcp wiring: one ClientManager, one client per Slack user.

The keycardai-mcp SDK does the heavy lifting for Keycard-protected MCP
servers. On a 401 it discovers the protected-resource metadata (RFC 9728),
registers itself as a public OAuth client via Dynamic Client Registration
(RFC 7591), and runs the authorization-code flow with PKCE. No client
secret is stored in this app; the MCP server side holds the confidential
credentials for its upstream providers.

Three pieces:

- SQLiteBackend persists per-user tokens and pending auth state on disk,
  so users only authorize once per server.
- StarletteAuthCoordinator handles the OAuth redirect. It does not run its
  own HTTP server; we mount its completion endpoint on our Starlette app
  at /oauth/callback (see main.py).
- ClientManager hands out one Client per context id. We use
  "slack:<user_id>" so every Slack user gets isolated token storage.
"""

from __future__ import annotations

import logging

from keycardai.mcp.client import Client, ClientManager, SQLiteBackend, StarletteAuthCoordinator
from keycardai.mcp.client.types import AuthChallenge

from slack_agent.config import ServerEntry

logger = logging.getLogger(__name__)


def build_manager(
    servers: list[ServerEntry],
    redirect_uri: str,
    db_path: str,
) -> tuple[ClientManager, StarletteAuthCoordinator]:
    """Create the shared ClientManager and its auth coordinator."""
    backend = SQLiteBackend(db_path)
    coordinator = StarletteAuthCoordinator(backend=backend, redirect_uri=redirect_uri)
    manager = ClientManager(
        servers={
            entry.key: {"url": entry.url, "auth": {"type": "oauth"}}
            for entry in servers
        },
        auth_coordinator=coordinator,
    )
    return manager, coordinator


def context_id_for(slack_user_id: str) -> str:
    return f"slack:{slack_user_id}"


def slack_user_from_context(context_id: str) -> str | None:
    """Inverse of context_id_for. Returns None for non-Slack contexts."""
    if context_id.startswith("slack:"):
        return context_id.removeprefix("slack:")
    return None


async def get_user_client(manager: ClientManager, slack_user_id: str) -> Client:
    """Get (or create) this user's MCP client and connect it.

    connect() never raises for ordinary failures. Sessions that need OAuth
    move to an auth-pending state; check client.get_auth_challenges()
    afterwards to see if the user must authorize. Repeat calls are cheap:
    already-healthy sessions are left alone.
    """
    client = await manager.get_client(context_id_for(slack_user_id))
    await client.connect()
    return client


async def force_reauth(client: Client, server_name: str) -> list[AuthChallenge]:
    """Drop a stale token and re-run the OAuth flow for one server.

    Called when a tool fails because the user's grant was revoked or expired
    upstream. The catch is that the session to the MCP server is still
    healthy (its own token is valid), so it never re-challenges on its own —
    only the delegated token exchange the MCP server does at call time fails.

    We delete just this server's stored token so the next request has no
    bearer, forcing a fresh 401 -> authorization flow (which re-consents the
    revoked grant), then reconnect and return the new challenge(s) to post.
    This is what lets the demo recover without deleting the token database.
    """
    oauth_storage = (
        client.context.storage_path()
        .for_server(server_name)
        .for_connection()
        .for_oauth()
        .build()
    )
    cleared = await oauth_storage.delete("tokens")
    if cleared:
        logger.info("Cleared stored token for %s; forcing re-auth", server_name)
    else:
        # No token at the expected key means the storage layout drifted: the
        # reconnect below won't get a 401 and we'd post a "reconnect" link that
        # cleared nothing. Surface it instead of silently claiming recovery.
        logger.warning(
            "force_reauth: no stored token found for %s at %s — storage layout "
            "may have changed",
            server_name,
            oauth_storage._namespace,
        )
    await client.connect(server_name, force_reconnect=True)
    return await client.get_auth_challenges(server_name)
