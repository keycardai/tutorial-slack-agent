# Tutorial: Build a Slack agent with Keycard

A minimal Slack AI agent that answers questions like "what's on my calendar
today?" from each user's own Google Calendar, through a Keycard-protected MCP
server. Each Slack user authorizes once (OAuth 2.0 with PKCE); every
downstream call runs as that user with a short-lived, scoped credential. No
shared service-account token, and every authorization is logged in Keycard.

This repository pairs with the step-by-step tutorial at
[docs.keycard.ai/guides/slack-agent](https://docs.keycard.ai/guides/slack-agent/),
which covers the Keycard Console configuration (Google provider, resources,
application, credentials) that both services need.

## Layout

| Directory | Service |
| --- | --- |
| [`agent/`](agent/) | The Slack bot: Bolt (Socket Mode) + a small Claude tool loop + a Keycard MCP client with per-user OAuth sessions. Needs no Keycard secret. |
| [`google-mcp-server/`](google-mcp-server/) | A Keycard-protected MCP server exposing Google Calendar, Drive, Docs, Gmail, and Sheets tools. Exchanges each user's token for a Google API token. |

```
Slack user ──▶ agent (MCP client, per-user PKCE) ──▶ google-mcp-server ──▶ Google API
                              └────────── Keycard (auth + token exchange) ──────┘
```

## Quickstart

Follow the [tutorial](https://docs.keycard.ai/guides/slack-agent/) for the
Keycard and Slack configuration. Then, in two terminals:

```bash
cd google-mcp-server
cp .env.example .env   # Keycard issuer + client credentials, see tutorial Part 3
uv sync
uv run python -m google_mcp_server
```

```bash
cd agent
cp .env.example .env   # Slack tokens + Anthropic key, see tutorial Part 4
uv sync
uv run slack-agent
```

Or run both with Docker Compose (after filling in both `.env` files):

```bash
docker compose up
```

Each service's own README covers its configuration and troubleshooting.

## License

MIT
