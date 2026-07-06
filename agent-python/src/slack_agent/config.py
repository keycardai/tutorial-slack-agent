"""Environment configuration.

All settings come from environment variables. See .env.example for the
full table. The app exits with a readable error when required variables
are missing, so a bare `uv run slack-agent` tells you exactly what to set.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Values already present in the environment win over .env entries.
load_dotenv()

REQUIRED_VARS = (
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "ANTHROPIC_API_KEY",
    "MCP_SERVERS",
)


@dataclass(frozen=True)
class ServerEntry:
    """One MCP server: a short key (used in tool names) and its URL."""

    key: str
    url: str


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    slack_app_token: str
    anthropic_api_key: str
    mcp_servers: list[ServerEntry]
    port: int
    base_url: str
    token_db_path: str

    @property
    def oauth_redirect_uri(self) -> str:
        return f"{self.base_url}/oauth/callback"


def load_settings() -> Settings:
    """Read and validate settings from the environment.

    Raises SystemExit with a friendly message when configuration is
    missing or malformed.
    """
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "Missing required environment variables: "
            + ", ".join(missing)
            + "\nCopy .env.example to .env, fill in the values, then run:"
            + "\n  uv run slack-agent"
        )

    raw_servers = os.environ["MCP_SERVERS"]
    try:
        entries = json.loads(raw_servers)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            "MCP_SERVERS is not valid JSON. Expected an array like:\n"
            '  [{"key": "google", "url": "http://localhost:8000/mcp"}]\n'
            "JSON needs double quotes around keys and values, with no "
            "backslash escapes and no quotes around the whole value.\n"
            f"Received: {raw_servers}\n"
            f"Parse error: {exc}"
        ) from exc

    servers: list[ServerEntry] = []
    if not isinstance(entries, list) or not entries:
        raise SystemExit("MCP_SERVERS must be a non-empty JSON array of {key, url} objects.")
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("key") or not entry.get("url"):
            raise SystemExit(
                f"Each MCP_SERVERS entry needs a 'key' and a 'url'. Bad entry: {entry!r}"
            )
        servers.append(ServerEntry(key=str(entry["key"]), url=str(entry["url"])))

    port = int(os.environ.get("PORT", "3000"))
    base_url = os.environ.get("BASE_URL", f"http://localhost:{port}").rstrip("/")

    return Settings(
        slack_bot_token=os.environ["SLACK_BOT_TOKEN"],
        slack_app_token=os.environ["SLACK_APP_TOKEN"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        mcp_servers=servers,
        port=port,
        base_url=base_url,
        token_db_path=os.environ.get("TOKEN_DB_PATH", "data/mcp-auth.db"),
    )
