"""A deliberately small Anthropic tool loop.

Flow per Slack message:

1. List the tools available on the user's MCP client and convert them to
   Anthropic tool definitions (namespaced "<server>__<tool>" so two servers
   can expose tools with the same name).
2. Call the model. If it wants tools, execute them through the user's MCP
   client, append the results, and loop.
3. Stop when the model answers in plain text or the iteration cap is hit.

No streaming, no memory, no persona. That is the point of this repo.
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
) -> tuple[str, bool]:
    """Run one MCP tool call. Returns (text_result, is_error)."""
    try:
        result = await client.call_tool(tool_name, arguments, server_name=server)
    except Exception as exc:
        logger.exception("MCP tool call failed: %s/%s", server, tool_name)
        return f"Error calling {server}/{tool_name}: {type(exc).__name__}: {exc}", True

    text_parts = [c.text for c in result.content if hasattr(c, "text")]
    text = "\n".join(text_parts) if text_parts else "(empty result)"
    return text, bool(result.isError)


async def run_agent(anthropic: AsyncAnthropic, client: Client, user_text: str) -> str:
    """Answer one user message, executing MCP tools as needed."""
    tool_infos = await client.list_tools()
    tools, routes = _tool_definitions(client, tool_infos)
    system = SYSTEM_PROMPT.format(today=datetime.now(UTC).strftime("%A, %Y-%m-%d"))

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]

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
            text, is_error = await _execute_tool(client, server, tool_name, dict(block.input))
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
