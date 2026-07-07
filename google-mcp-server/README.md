# Google MCP Server

A remote [MCP](https://modelcontextprotocol.io/) server for Google Calendar, Drive, Docs, Gmail, and Sheets, protected by [Keycard](https://keycard.ai).

Keycard sits in front of the server and handles the OAuth work: it authenticates incoming MCP clients, runs the Google consent flow for each user, and exchanges the caller's token for a Google API access token on every tool call. The server itself never stores Google credentials.

## Features

- **Calendar**: list calendars, list/search events, create, update, and delete events
- **Drive**: search and list files, get metadata, download or export content, delete files
- **Docs**: create documents, read content, append and replace text
- **Gmail**: search, read, and send email, drafts, labels, threads, archive/trash
- **Sheets**: create spreadsheets, read/write/append/clear values, add sheet tabs, batch reads

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (or Docker)
- A [Keycard](https://keycard.ai) account with a zone
- A Google Cloud project with the Calendar, Drive, Docs, Gmail, and Sheets APIs enabled, and an OAuth client for Keycard to use

## Keycard setup

In the [Keycard Console](https://console.keycard.ai):

1. **Add Google as a resource** in your zone, using your Google OAuth client ID and secret. Configure the scopes the tools need:
   - `https://www.googleapis.com/auth/calendar`
   - `https://www.googleapis.com/auth/drive`
   - `https://www.googleapis.com/auth/documents`
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/spreadsheets`
2. **Register this MCP server** in the zone, with its public URL (for local development, `http://localhost:8000`).
3. **Create client credentials** for the MCP server and note the client ID and secret.
4. **Grant the server access** to the Google resource.

See the [Keycard docs](https://docs.keycard.ai) for a full walkthrough of each step.

## Configuration

Copy `.env.example` to `.env` and fill in your values:

| Variable | Required | Description |
| --- | --- | --- |
| `KEYCARD_ISSUER` | Yes | Your Keycard zone URL, e.g. `https://your-zone-id.keycard.cloud` |
| `KEYCARD_CLIENT_ID` | Yes* | Client ID issued by Keycard for this MCP server |
| `KEYCARD_CLIENT_SECRET` | Yes* | Client secret issued by Keycard for this MCP server |
| `KEYCARD_CREDENTIAL_TYPE` | No | `client_secret` (default) or `web_identity` |
| `KEYCARD_WEB_IDENTITY_KEY_STORAGE_DIR` | No | Key storage directory for `web_identity` (default `./server_keys`) |
| `MCP_SERVER_URL` | Yes | Public URL of this server, as registered in Keycard (default `http://localhost:8000`) |
| `GOOGLE_API_RESOURCE` | Yes | Resource identifier of the Google API as registered in Keycard. Must match the Keycard resource exactly; the catalog Google Calendar resource is `https://www.googleapis.com/calendar/v3`. A mismatch fails at the first tool call with "Token exchange failed" |
| `PORT` | No | Port to listen on (default `8000`) |

\* Required with the default `client_secret` credential type.

## Run locally

```bash
cp .env.example .env   # then fill in your Keycard values
uv sync
uv run python -m google_mcp_server
```

The server listens on `http://localhost:8000` with:

- `/mcp` - MCP endpoint (Streamable HTTP)
- `/health` - health check
- `/.well-known/jwks.json` - public keys (used with the `web_identity` credential type)

Connect with any MCP client, for example [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector
```

Point it at `http://localhost:8000/mcp`. Keycard drives the OAuth flow: sign in, consent to Google access, and the tools become available.

## Run with Docker

```bash
cp .env.example .env   # then fill in your Keycard values
docker compose up --build
```

## Alternative: workload identity (no client secret)

Instead of a client secret, the server can authenticate to Keycard with a private key JWT. Set:

```bash
KEYCARD_CREDENTIAL_TYPE=web_identity
```

On first boot the server generates a key pair in `KEYCARD_WEB_IDENTITY_KEY_STORAGE_DIR` and serves the public key at `/.well-known/jwks.json`. Register that JWKS URL (or the public key) as the server's credential in the Keycard Console instead of creating a client secret. Use persistent storage for the key directory so the identity survives restarts.

## Deploy

The server is a single container listening on `$PORT`, so any container platform works. Set the environment variables from the table above, with `MCP_SERVER_URL` set to the deployment's public URL (and the same URL registered in Keycard).

- **Render**: create a Web Service from this repo using the Dockerfile. Render injects `PORT` automatically.
- **Fly.io**: `fly launch` picks up the Dockerfile. Set secrets with `fly secrets set KEYCARD_ISSUER=... KEYCARD_CLIENT_ID=... KEYCARD_CLIENT_SECRET=...`. If you use `web_identity`, mount a volume for the key storage directory.

## Tools

### Calendar
- `list_calendars` - List the user's Google calendars
- `list_events` - List/search events with time range filtering and text search
- `get_event` - Get details of a specific event
- `create_event` - Create a new calendar event with attendees
- `update_event` - Update an existing event's fields
- `delete_event` - Delete a calendar event

### Docs
- `create_document` - Create a new blank Google Doc
- `read_document` - Read the text content of a Google Doc
- `append_text` - Append text to the end of a Google Doc
- `replace_text` - Find and replace text in a Google Doc

### Drive
- `list_files` - List/search files with Drive query syntax
- `get_file` - Get file metadata (name, type, size, links)
- `get_file_content` - Download file content or export Google Workspace docs
- `delete_file` - Delete a file

### Gmail
- `search_emails` - Search messages with Gmail query syntax
- `read_email` - Read full email content with headers and attachments
- `send_email` - Send an email
- `create_draft` - Create a draft email
- `get_thread` - Get all messages in a conversation thread
- `list_labels` - List all Gmail labels
- `modify_message` - Add/remove labels (mark read, archive, star, etc.)
- `trash_message` - Move a message to trash

### Sheets
- `create_spreadsheet` - Create a new Google Spreadsheet
- `get_spreadsheet` - Get spreadsheet metadata and list of sheet tabs
- `get_values` - Read cell values from a range (A1 notation)
- `update_values` - Write values to a range
- `append_values` - Append rows to a range/table
- `clear_values` - Clear cell values in a range
- `add_sheet` - Add a new sheet (tab) to a spreadsheet
- `batch_get_values` - Read values from multiple ranges in one call

## License

[MIT](LICENSE)
