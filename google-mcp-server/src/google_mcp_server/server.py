"""FastMCP server definition for the Google MCP Server.

Creates the FastMCP instance with Keycard authentication and registers
all Google tools. Run it with:

    uv run python -m google_mcp_server
"""

import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from .auth import auth_provider
from .tools.calendars import register_calendar_tools
from .tools.docs import register_docs_tools
from .tools.drive import register_drive_tools
from .tools.gmail import register_gmail_tools
from .tools.sheets import register_sheets_tools

load_dotenv()


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server instance.

    Returns:
        Configured FastMCP instance with Keycard auth and all tools registered.
    """
    auth = auth_provider.get_remote_auth_provider()

    mcp = FastMCP(
        "Google MCP Server",
        auth=auth,
        instructions="""Google MCP Server for Calendar, Drive, Docs, Gmail, and Sheets operations.

This server provides tools to:
- List calendars and manage calendar events (create, update, delete)
- Search and list Google Drive files
- Get file metadata and download file content
- Delete Drive files
- Create, read, and edit Google Docs
- Search, read, and send Gmail messages
- Manage Gmail drafts, labels, and threads
- Create spreadsheets and read/write cell values in Google Sheets
- Add sheet tabs and batch-read ranges

Authentication is handled via Keycard OAuth.
""",
    )

    register_calendar_tools(mcp)
    register_docs_tools(mcp)
    register_drive_tools(mcp)
    register_gmail_tools(mcp)
    register_sheets_tools(mcp)

    return mcp


mcp = create_mcp_server()


def main() -> None:
    """Run the HTTP server with health and JWKS endpoints."""
    import logging

    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    logging.basicConfig(level=logging.INFO)
    port = int(os.getenv("PORT", 8000))

    def jwks_handler(request: Request) -> JSONResponse:
        # Serves the server's public keys when using the web_identity
        # credential type. Returns an empty key set otherwise.
        cred = auth_provider.application_credential
        if cred is None or not hasattr(cred, "get_jwks"):
            return JSONResponse({"keys": []})
        return JSONResponse(cred.get_jwks().model_dump(exclude_none=True))

    def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    mcp_http = mcp.http_app()
    app = Starlette(
        routes=[
            Route("/.well-known/jwks.json", jwks_handler),
            Route("/health", health),
            Mount("/", app=mcp_http),
        ],
        lifespan=mcp_http.lifespan,
    )
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
