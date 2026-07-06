"""Process entry point.

Runs two things side by side in one asyncio loop:

- uvicorn serving a tiny Starlette app on PORT. Its only real route is
  /oauth/callback, the OAuth redirect target for MCP authorization.
  For local runs the user's browser hits http://localhost:PORT directly,
  so no tunnel is needed.
- slack-bolt's Socket Mode handler, which keeps a websocket open to Slack
  so the bot needs no public URL for events either.
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn
from anthropic import AsyncAnthropic
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from slack_agent.bot import AuthCompletionNotifier, build_app
from slack_agent.config import load_settings
from slack_agent.mcp import build_manager

logger = logging.getLogger(__name__)


async def _health(_request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    settings = load_settings()

    manager, coordinator = build_manager(
        servers=settings.mcp_servers,
        redirect_uri=settings.oauth_redirect_uri,
        db_path=settings.token_db_path,
    )

    anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    slack_app = build_app(settings, manager, anthropic)
    coordinator.subscribe(AuthCompletionNotifier(slack_app.client))

    web = Starlette(
        routes=[
            Route("/oauth/callback", coordinator.get_completion_endpoint(), methods=["GET"]),
            Route("/healthz", _health, methods=["GET"]),
        ]
    )
    server = uvicorn.Server(
        uvicorn.Config(web, host="0.0.0.0", port=settings.port, log_level="info")
    )
    socket_mode = AsyncSocketModeHandler(slack_app, settings.slack_app_token)

    logger.info(
        "Starting: OAuth callback at %s, MCP servers: %s",
        settings.oauth_redirect_uri,
        [entry.key for entry in settings.mcp_servers],
    )
    await asyncio.gather(server.serve(), socket_mode.start_async())


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
