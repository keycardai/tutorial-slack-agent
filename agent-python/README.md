# tutorial-slack-agent

A minimal Slack AI agent that connects to [Keycard](https://keycard.ai)-protected
MCP servers with per-user OAuth. Each Slack user authorizes once in the browser;
after that the agent calls MCP tools *as that user*.

The demo flow:

1. You DM the bot (or @mention it): "what's on my calendar today?"
2. The agent needs Google Calendar tools from a Keycard-protected Google MCP
   server, but you haven't authorized yet, so it posts an authorization link.
3. You click the link and approve access via Keycard (OAuth 2.0 authorization
   code flow with PKCE).
4. The bot DMs you "Connected!". You ask again, and the agent lists your
   calendar events by calling MCP tools with *your* credentials.

This is a teaching repo, distilled from a production agent. It deliberately has
no streaming, no database, no risk tiers, no hot reload. Read it top to bottom
in one sitting.

## Architecture

```
        Slack workspace                         your machine / one container
  ┌──────────────────────────┐          ┌─────────────────────────────────────────┐
  │  user DMs / @mentions    │◄────────►│  slack-bolt AsyncApp (Socket Mode)      │
  └──────────────────────────┘ websocket│      │                                  │
                                        │      ▼                                  │
        user's browser                  │  agent loop (anthropic, tool use)       │
  ┌──────────────────────────┐          │      │                                  │
  │  Keycard authorize page  │          │      ▼                                  │
  └────────────┬─────────────┘          │  keycardai-mcp ClientManager            │
               │ redirect               │   one Client per Slack user             │
               ▼                        │   tokens in SQLite (data/mcp-auth.db)   │
  ┌──────────────────────────┐   HTTP   │      │                                  │
  │ GET /oauth/callback ─────┼─────────►│  Starlette + uvicorn on PORT (3000)     │
  └──────────────────────────┘          └──────┼──────────────────────────────────┘
                                               │ streamable HTTP + Bearer token
                                               ▼
                                  Keycard-protected MCP server(s)
                                  (e.g. Google MCP: Calendar, Gmail, ...)
```

Because Slack events arrive over Socket Mode (an outbound websocket) and the
OAuth callback is hit by *your own browser* at `http://localhost:3000`, local
development needs **no public URL and no tunnel**.

The agent itself holds **no Keycard client secret**. The keycardai-mcp SDK
registers it as a public OAuth client via Dynamic Client Registration
(RFC 7591) and authenticates users with PKCE. The MCP server is the
confidential party that holds provider credentials.

## Source tour

| File | What it does |
|---|---|
| `src/slack_agent/config.py` | Reads and validates env vars, fails fast with a clear message |
| `src/slack_agent/mcp.py` | ClientManager + StarletteAuthCoordinator + SQLiteBackend wiring |
| `src/slack_agent/agent.py` | The ~100 line Anthropic tool loop |
| `src/slack_agent/history.py` | Fetches the recent Slack thread and converts it to Anthropic messages |
| `src/slack_agent/bot.py` | Slack handlers, auth-link message, auth-complete DM |
| `src/slack_agent/main.py` | Runs uvicorn (OAuth callback) and Socket Mode together |

## Conversation memory

The agent keeps no conversation state of its own. On every turn it re-reads
the last 12 messages of the Slack conversation (the DM, or the channel
thread) and replays them to Claude. Slack is the transcript: there is
nothing to persist, nothing to migrate, and follow-up questions keep
working across restarts.

This needs the `channels:history` bot scope to read channel threads
(`im:history` already covers DMs). If you created the Slack app before this
scope was in `manifest.json`, add it and reinstall the app to your
workspace.

## Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/)
- **A Slack workspace** where you can install apps
- **An Anthropic API key** ([console.anthropic.com](https://console.anthropic.com))
- **A running Keycard-protected MCP server**, e.g. a Google MCP server whose
  zone has your user and the relevant resource scopes configured. You need its
  URL (usually ending in `/mcp`). Setting one up is covered by the Keycard docs;
  this repo only consumes it.

## 1. Create the Slack app

1. Go to [api.slack.com/apps](https://api.slack.com/apps) > **Create New App** >
   **From a manifest**, pick your workspace, and paste the contents of
   [`manifest.json`](manifest.json).
2. On **Basic Information** > **App-Level Tokens**, generate a token with the
   `connections:write` scope. That is your `SLACK_APP_TOKEN` (`xapp-...`).
3. On **Install App**, install it to your workspace and copy the
   **Bot User OAuth Token**. That is your `SLACK_BOT_TOKEN` (`xoxb-...`).

## 2. Configure

```bash
git clone <this-repo>
cd tutorial-slack-agent
cp .env.example .env
# edit .env: Slack tokens, Anthropic key, and your MCP server URL(s)
```

`MCP_SERVERS` is a JSON array so you can plug in more than one server:

```json
[{"key":"google","url":"https://your-google-mcp.example.com/mcp"}]
```

The `key` becomes the tool-name prefix the model sees (`google__list_events`).

## 3. Run

```bash
uv sync
uv run slack-agent
```

You should see uvicorn listening on port 3000 and Bolt's
"Socket Mode client is connected" message.

## 4. Test

1. In Slack, open a DM with the bot (or invite it to a channel and @mention it).
2. Ask: `what's on my calendar today?`
3. First time only: the bot replies with a **Connect google** link. Open it,
   authorize via Keycard, and wait for the "Connected" DM.
4. Ask again. The agent lists tools from the MCP server, calls
   `google__list_events` with your token, and answers with your actual events.

## Troubleshooting

**The auth link errors or says the callback failed.**
Authorization links contain one-time PKCE state. If you waited a long time or
restarted the agent between getting the link and clicking it, ask the bot
again to get a fresh link.

**I want to force a user to re-authorize.**
Tokens live in a single SQLite file. Stop the agent and delete it:

```bash
rm data/mcp-auth.db
```

Everyone re-authorizes on their next question. (Fine for a tutorial; a real
deployment would delete only that user's keys.)

**The bot doesn't respond to DMs.**
Check the app was created from `manifest.json` (it needs the `message.im`
event and `im:history` scope) and that Socket Mode connected in the logs.
After changing the manifest, reinstall the app to your workspace.

**"Missing required environment variables" on startup.**
The message lists exactly which ones. The agent loads `.env` from the
directory you run it in, so run it from `agent-python/` where your `.env`
lives.

**Tool calls fail with 401 after previously working.**
The stored token may have expired or been revoked in Keycard. Delete
`data/mcp-auth.db` (see above) and re-authorize.

## Docker

```bash
docker compose up --build
```

Tokens persist in the `agent-data` volume. The compose file reads `.env` for
configuration.

## Deploying somewhere real

The agent runs anywhere a container runs (Fly.io, Render, a VM). Two things
change from local dev:

- Set `BASE_URL` to your public HTTPS URL (e.g. `https://my-agent.fly.dev`)
  so authorization links redirect back to `https://.../oauth/callback`.
  Slack events still arrive over Socket Mode, so only the callback needs to
  be reachable.
- Put `data/` on a persistent volume, or users re-authorize on every deploy.

## License

MIT, see [LICENSE](LICENSE).
