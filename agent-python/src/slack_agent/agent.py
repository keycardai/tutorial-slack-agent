"""A deliberately small Anthropic tool loop.

Flow per Slack message:

1. List the tools available on the user's MCP client and convert them to
   Anthropic tool definitions (namespaced "<server>__<tool>" so two servers
   can expose tools with the same name).
2. Call the model. If it wants tools, execute them through the user's MCP
   client, append the results, and loop.
3. Stop when the model answers in plain text or the iteration cap is hit.

No streaming, no persona, no conversation store. Memory is the recent
Slack thread, fetched by the caller and passed in as the message list.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from anthropic import AsyncAnthropic
from keycardai.mcp.client import Client

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_ITERATIONS = 10


class ReauthRequired(Exception):
    """A tool failed because the user's authorization is no longer valid.

    Revoking a grant in Keycard (or an expired upstream grant) kills the
    delegated token exchange the MCP server does at call time, while the
    client's own session to the MCP server stays connected. So the session
    still looks operational and no auth challenge fires; the only signal is
    the failure inside the tool result. The bot catches this to re-run the
    OAuth flow for the named server.
    """

    def __init__(self, server: str) -> None:
        super().__init__(f"Re-authorization required for {server}")
        self.server = server


# The exact prefix get_google_token() raises (and the MCP tools return in the
# "error" field) when the delegated grant is missing/revoked/expired. Anchor on
# the structured error field, not the rendered text: the server this tutorial
# ships is Google (Gmail/Calendar/Drive/Docs), where auth-ish strings are
# ordinary content — a security-alert email, a doc titled "authentication
# errors runbook" — and must not be mistaken for a real auth failure.
_AUTH_ERROR_PREFIX = "Authentication errors:"


def _is_auth_failure(structured: dict[str, Any] | None) -> bool:
    """True only for the structured auth-failure shape the MCP tools return.

    The Google tools return failures as {"success": False, "error": ...,
    "isError": True}; a revoked/expired grant sets "error" to the
    "Authentication errors: ..." message. Ordinary Google API errors set a
    different message, and successful results have no top-level "error", so
    this never fires on real content or on unrelated tool errors.
    """
    if not isinstance(structured, dict):
        return False
    error = structured.get("error")
    return isinstance(error, str) and error.startswith(_AUTH_ERROR_PREFIX)

SYSTEM_PROMPT = """\
You are a helpful assistant living in Slack. Answer concisely in Slack style:
plain text, short paragraphs, no markdown headers.

You have tools from one or more MCP servers. Tool names are prefixed with the
server they come from (for example google__list_events). Use them whenever the
user's question needs live data, and answer from the results.

Today's date (UTC): {today}
"""


def _tool_definitions(client: Client, tool_infos: list[Any]) -> tuple[list[dict[str, Any]], dict[str, tuple[str, str]]]:
    """Convert MCP tools to Anthropic tool definitions.

    Returns the definitions plus a routing map from the namespaced
    Anthropic tool name back to (server, mcp_tool_name).
    """
    definitions: list[dict[str, Any]] = []
    routes: dict[str, tuple[str, str]] = {}
    for info in tool_infos:
        name = f"{info.server}__{info.tool.name}"[:128]
        routes[name] = (info.server, info.tool.name)
        definitions.append(
            {
                "name": name,
                "description": info.tool.description or info.tool.name,
                "input_schema": info.tool.inputSchema
                or {"type": "object", "properties": {}},
            }
        )
    return definitions, routes


async def _execute_tool(
    client: Client, server: str, tool_name: str, arguments: dict[str, Any]
) -> tuple[str, bool, dict[str, Any] | None]:
    """Run one MCP tool call.

    Returns (text_result, is_error, structured_content). structured_content is
    the tool's structured return (the dict the Google tools produce) when the
    MCP result carries one, else None — used to detect an auth failure at the
    boundary instead of string-matching the rendered text.
    """
    try:
        result = await client.call_tool(tool_name, arguments, server_name=server)
    except Exception as exc:
        logger.exception("MCP tool call failed: %s/%s", server, tool_name)
        return f"Error calling {server}/{tool_name}: {type(exc).__name__}: {exc}", True, None

    text_parts = [c.text for c in result.content if hasattr(c, "text")]
    text = "\n".join(text_parts) if text_parts else "(empty result)"
    structured = getattr(result, "structuredContent", None)
    return text, bool(result.isError), structured


async def run_agent(
    anthropic: AsyncAnthropic, client: Client, messages: list[dict[str, Any]]
) -> str:
    """Answer the latest user message, executing MCP tools as needed.

    The caller supplies the conversation so far (recent Slack history plus
    the current question, ending with a user message). The tool loop
    appends tool_use and tool_result turns to that same list.
    """
    tool_infos = await client.list_tools()
    tools, routes = _tool_definitions(client, tool_infos)
    system = SYSTEM_PROMPT.format(today=datetime.now(UTC).strftime("%A, %Y-%m-%d"))

    for _ in range(MAX_ITERATIONS):
        response = await anthropic.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return text or "(no response)"

        messages.append({"role": "assistant", "content": response.content})

        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            server, tool_name = routes[block.name]
            logger.info("tool call: %s/%s", server, tool_name)
            text, is_error, structured = await _execute_tool(
                client, server, tool_name, dict(block.input)
            )
            # A revoked/expired grant comes back as a structured error (the tool
            # returns a dict, so is_error stays False). Detect that specific
            # shape and let the bot re-run OAuth rather than feeding the model
            # an auth error it can't recover from.
            if _is_auth_failure(structured):
                raise ReauthRequired(server)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": text,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return "I hit my tool-call limit answering that. Try asking something narrower."
