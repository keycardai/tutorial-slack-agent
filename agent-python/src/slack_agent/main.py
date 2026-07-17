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
from keycardai.mcp.client import StarletteAuthCoordinator
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from slack_agent.bot import AuthCompletionNotifier, build_app
from slack_agent.config import load_settings
from slack_agent.mcp import build_manager

logger = logging.getLogger(__name__)

# Shown when someone opens an authorization link whose one-time state is no
# longer valid — almost always a stale link (already used, expired, or from a
# previous run). The SDK would otherwise return a generic 500 here.
_EXPIRED_LINK_HTML = """\
<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Link expired</title>
    <style>
      :root { color-scheme: light dark; }
      body { font-family: system-ui, -apple-system, sans-serif; margin: 0;
             min-height: 100vh; display: flex; align-items: center;
             justify-content: center; text-align: center; padding: 1.5rem; }
      .card { max-width: 26rem; }
      h1 { font-size: 1.25rem; margin: 0 0 .5rem; }
      p { margin: .25rem 0; opacity: .8; line-height: 1.5; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>This authorization link has expired</h1>
      <p>It may have already been used or come from an earlier attempt.</p>
      <p>Head back to Slack, ask me again, and click the newest link I send.</p>
      <p>You can close this tab.</p>
    </div>
  </body>
</html>
"""


def _oauth_callback(coordinator: StarletteAuthCoordinator):
    """The SDK completion endpoint, with a friendly page for stale links.

    Each OAuth flow stores a one-time completion route keyed by its state and
    deletes it once used. If the state has no route, the link is stale/expired
    /already-used, so we return a readable page instead of the SDK's generic
    500. Any other failure still falls through to the SDK handler.
    """
    inner = coordinator.get_completion_endpoint()

    async def endpoint(request):
        state = request.query_params.get("state")
        if state and await coordinator.state_store.get_completion_route(state) is None:
            return HTMLResponse(_EXPIRED_LINK_HTML, status_code=410)
        return await inner(request)

    return endpoint


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
            Route("/oauth/callback", _oauth_callback(coordinator), methods=["GET"]),
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
