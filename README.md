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
| [`agent-python/`](agent-python/) | The Slack bot in Python: Bolt (Socket Mode) + a small Claude tool loop + the Keycard MCP client (`keycardai-mcp` `ClientManager`) with per-user OAuth sessions. Needs no Keycard secret. |
| [`agent-typescript/`](agent-typescript/) | The same bot in TypeScript: Bolt (Socket Mode) + a small Claude tool loop + the official MCP SDK client wired through `@keycardai/mcp`'s `BaseOAuthClientProvider` with per-user OAuth sessions. Needs no Keycard secret. |
| [`google-mcp-server/`](google-mcp-server/) | A Keycard-protected MCP server exposing Google Calendar, Drive, Docs, Gmail, and Sheets tools. Exchanges each user's token for a Google API token. |

Both agents implement the same flow; pick the language you'd build in. Run
only one at a time: they share the same Slack app, so running both answers
every message twice.

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
# Python agent
cd agent-python
cp .env.example .env   # Slack tokens + Anthropic key, see tutorial Part 4
uv sync
uv run slack-agent

# or the TypeScript agent
cd agent-typescript
cp .env.example .env
npm install
npm run dev
```

Or with Docker Compose (after filling in the `.env` files), picking one agent:

```bash
docker compose --profile python up      # or --profile typescript
```

Each service's own README covers its configuration and troubleshooting.

## License

MIT
