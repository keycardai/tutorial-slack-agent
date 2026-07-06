# tutorial-slack-agent (TypeScript)

A minimal Slack AI agent that connects to [Keycard](https://keycard.ai)-protected
MCP servers with per-user OAuth. Each Slack user authorizes once in the browser;
after that the agent calls MCP tools *as that user*.

This is the TypeScript variant of the tutorial; the Python variant lives in
[`../agent-python`](../agent-python). Both implement the same UX and share the
same Slack app manifest, so you can run either one against the same Slack app.

The demo flow:

1. You DM the bot (or @mention it): "what's on my calendar today?"
2. The agent needs Google Calendar tools from a Keycard-protected Google MCP
   server, but you haven't authorized yet, so it posts an authorization link.
3. You click the link and approve access via Keycard (OAuth 2.0 authorization
   code flow with PKCE).
4. The bot DMs you "Connected!". You ask again, and the agent lists your
   calendar events by calling MCP tools with *your* credentials.

This is a teaching repo, distilled from a production agent. It deliberately has
no streaming, no memory, no risk tiers, no hot reload. Read it top to bottom in
one sitting.

## Architecture

```
        Slack workspace                         your machine / one container
  ┌──────────────────────────┐          ┌─────────────────────────────────────────┐
  │  user DMs / @mentions    │◄────────►│  @slack/bolt App (Socket Mode)          │
  └──────────────────────────┘ websocket│      │                                  │
                                        │      ▼                                  │
        user's browser                  │  agent loop (@anthropic-ai/sdk)         │
  ┌──────────────────────────┐          │      │                                  │
  │  Keycard authorize page  │          │      ▼                                  │
  └────────────┬─────────────┘          │  MCP SDK Client, one per Slack user     │
               │ redirect               │   auth via @keycardai/mcp provider      │
               ▼                        │   tokens in JSON (data/mcp-auth.json)   │
  ┌──────────────────────────┐   HTTP   │      │                                  │
  │ GET /oauth/callback ─────┼─────────►│  Express on PORT (3000)                 │
  └──────────────────────────┘          └──────┼──────────────────────────────────┘
                                               │ streamable HTTP + Bearer token
                                               ▼
                                  Keycard-protected MCP server(s)
                                  (e.g. Google MCP: Calendar, Gmail, ...)
```

Because Slack events arrive over Socket Mode (an outbound websocket) and the
OAuth callback is hit by *your own browser* at `http://localhost:3000`, local
development needs **no public URL and no tunnel**.

The agent itself holds **no Keycard client secret**. On the first 401 the MCP
SDK discovers the protected-resource metadata (RFC 9728), registers the agent
as a public OAuth client via Dynamic Client Registration (RFC 7591), and runs
the authorization-code flow with PKCE. The per-user plumbing (where tokens
live, where the auth link goes, how the callback finds its way back) is a
small subclass of `BaseOAuthClientProvider` from `@keycardai/mcp`. The MCP
server is the confidential party that holds provider credentials.

> **Note on versions**: this tutorial pins `@modelcontextprotocol/sdk` v1
> (`^1`). SDK v2 lands soon with a different client auth API; the flow here
> (connect throws `UnauthorizedError`, then `transport.finishAuth(code)`)
> is the v1 shape.

## Source tour

| File | What it does |
|---|---|
| `src/config.ts` | Reads and validates env vars, fails fast with a clear message |
| `src/storage.ts` | One JSON file for tokens, PKCE verifiers, and client registrations |
| `src/oauth-provider.ts` | `BaseOAuthClientProvider` subclass: DCR persistence, Slack redirect, routable state |
| `src/mcp.ts` | One MCP Client per (Slack user, server); connect and callback completion |
| `src/agent.ts` | The ~100 line Anthropic tool loop |
| `src/bot.ts` | Slack handlers and the auth-link message |
| `src/main.ts` | Runs Express (OAuth callback) and Socket Mode together |

## Prerequisites

- **Node.js 20+**
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
cd tutorial-slack-agent/agent-typescript
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
npm install
npm run build
node --env-file=.env dist/main.js
```

You should see the callback server listening on port 3000 and
"Slack Socket Mode connected."

For development with instant restarts on save:

```bash
npx tsx --env-file=.env src/main.ts
```

(`npm run dev` runs the same entry point via tsx, reading configuration from
the environment; `node --env-file` and `tsx --env-file` are the easiest ways
to load `.env`.)

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
Tokens live in a single JSON file. Stop the agent and delete it:

```bash
rm data/mcp-auth.json
```

Everyone re-authorizes on their next question. (Fine for a tutorial; a real
deployment would delete only that user's keys.)

**The bot doesn't respond to DMs.**
Check the app was created from `manifest.json` (it needs the `message.im`
event and `im:history` scope) and that Socket Mode connected in the logs.
After changing the manifest, reinstall the app to your workspace.

**"Missing required environment variables" on startup.**
The message lists exactly which ones. Make sure you loaded `.env`, e.g.
`node --env-file=.env dist/main.js` (a bare `npm start` reads only the
process environment).

**Tool calls fail with 401 after previously working.**
The stored token may have expired or been revoked in Keycard. Delete
`data/mcp-auth.json` (see above) and re-authorize.

## Docker

```bash
docker build -t tutorial-slack-agent-ts .
docker run --env-file .env -p 3000:3000 -v agent-data:/app/data tutorial-slack-agent-ts
```

Tokens persist in the `agent-data` volume.

## Deploying somewhere real

The agent runs anywhere a container runs (Fly.io, Render, a VM). Two things
change from local dev:

- Set `BASE_URL` to your public HTTPS URL (e.g. `https://my-agent.fly.dev`)
  so authorization links redirect back to `https://.../oauth/callback`.
  Slack events still arrive over Socket Mode, so only the callback needs to
  be reachable.
- Put `data/` on a persistent volume, or users re-authorize on every deploy.

## License

MIT, see [LICENSE](../LICENSE).
