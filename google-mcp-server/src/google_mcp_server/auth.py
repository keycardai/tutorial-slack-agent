"""Keycard authentication provider for the Google MCP Server.

Configures a Keycard AuthProvider that protects the MCP server and
exchanges incoming user tokens for Google API access tokens.

Two application credential types are supported, selected via
KEYCARD_CREDENTIAL_TYPE:

- "client_secret" (default): client credentials issued by Keycard.
  Requires KEYCARD_CLIENT_ID and KEYCARD_CLIENT_SECRET.
- "web_identity": workload identity federation (private key JWT).
  The server generates and stores its own key pair; register its public
  key (served at /.well-known/jwks.json) with Keycard instead of a secret.
"""

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from keycardai.fastmcp import AuthProvider
from keycardai.oauth.server.credentials import ClientSecret, WebIdentity

if TYPE_CHECKING:
    from keycardai.fastmcp import AccessContext

load_dotenv()

# Resource identifier of the Google API as registered in Keycard. Tool
# grants and token exchange target this resource, so it must match the
# resource identifier configured in the Keycard Console exactly.
GOOGLE_API_URL = os.getenv("GOOGLE_API_RESOURCE", "https://www.googleapis.com")

SERVER_NAME = "Google MCP Server"


def _build_application_credential() -> ClientSecret | WebIdentity:
    credential_type = os.getenv("KEYCARD_CREDENTIAL_TYPE", "client_secret")

    if credential_type == "web_identity":
        return WebIdentity(
            server_name=SERVER_NAME,
            storage_dir=os.getenv(
                "KEYCARD_WEB_IDENTITY_KEY_STORAGE_DIR", "./server_keys"
            ),
        )

    if credential_type != "client_secret":
        raise RuntimeError(
            f"Unsupported KEYCARD_CREDENTIAL_TYPE: {credential_type!r}. "
            'Use "client_secret" (default) or "web_identity".'
        )

    client_id = os.getenv("KEYCARD_CLIENT_ID")
    client_secret = os.getenv("KEYCARD_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "KEYCARD_CLIENT_ID and KEYCARD_CLIENT_SECRET are required. "
            "Create client credentials for this MCP server in the Keycard "
            "Console and set them in your environment (see .env.example)."
        )
    return ClientSecret((client_id, client_secret))


def _require_issuer() -> str:
    issuer = os.getenv("KEYCARD_ISSUER")
    if not issuer:
        raise RuntimeError(
            "KEYCARD_ISSUER is required. Set it to your Keycard zone URL, "
            "e.g. https://your-zone-id.keycard.cloud (see .env.example)."
        )
    return issuer


auth_provider = AuthProvider(
    zone_url=_require_issuer(),
    mcp_server_name=SERVER_NAME,
    mcp_server_url=os.getenv("MCP_SERVER_URL", "http://localhost:8000/"),
    application_credential=_build_application_credential(),
)


def get_google_token(access_ctx: "AccessContext") -> str:
    """Extract the Google API access token from a Keycard access context."""
    if access_ctx is None:
        raise ValueError("No authentication context")
    if access_ctx.has_errors():
        raise ValueError(f"Authentication errors: {access_ctx.get_errors()}")
    return access_ctx.access(GOOGLE_API_URL).access_token
