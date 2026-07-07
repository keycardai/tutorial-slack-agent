"""Slack ingress: a slack-bolt AsyncApp running in Socket Mode.

Two entry points, both funneled into one handler:

- @mentions in channels (app_mention events), replied to in-thread
- direct messages (message.im events), replied to in the DM

Auth UX: if any MCP server needs OAuth for this user, we post the
authorization link(s) instead of answering. After the user authorizes in
the browser, AuthCompletionNotifier DMs them to try again. Simple and
stateless: no automatic resume of the original question.
"""

from __future__ import annotations

import logging
import re

from anthropic import AsyncAnthropic
from keycardai.mcp.client import ClientManager
from keycardai.mcp.client.auth.events import CompletionEvent
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from slack_agent.agent import run_agent
from slack_agent.config import Settings
from slack_agent.mcp import get_user_client, slack_user_from_context

logger = logging.getLogger(__name__)

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


class AuthCompletionNotifier:
    """Subscribes to OAuth completions and pings the user in Slack.

    The coordinator notifies subscribers after each /oauth/callback hit.
    The completion result carries the context id ("slack:<user_id>") and
    the server name, which is all we need to send a DM.
    """

    def __init__(self, slack_client: AsyncWebClient) -> None:
        self._slack = slack_client

    async def on_completion_handled(self, event: CompletionEvent) -> None:
        if not event.success:
            return
        user_id = slack_user_from_context(str(event.result.get("context_id", "")))
        if not user_id:
            return
        server = event.result.get("server_name", "the MCP server")
        try:
            await self._slack.chat_postMessage(
                channel=user_id,
                text=f":white_check_mark: Connected to *{server}*. Ask me your question again!",
            )
        except Exception:
            logger.exception("Failed to send auth-complete DM to %s", user_id)


def _session_operational(client, server_name: str | None) -> bool:
    """True if the named server's session is connected and usable."""
    if not server_name:
        return False
    session = client.sessions.get(server_name)
    return bool(session and session.is_operational)


def _format_auth_prompt(challenges: list[dict]) -> str:
    lines = [
        "Before I can help, you need to connect your account(s). "
        "Click to authorize (the link is personal to you):",
    ]
    for challenge in challenges:
        server = challenge.get("server", "server")
        url = challenge.get("authorization_url")
        if url:
            lines.append(f"• <{url}|Connect {server}>")
        else:
            lines.append(f"• {server}: authorization required but no URL was issued")
    lines.append("When you're done, ask me again.")
    return "\n".join(lines)


def build_app(settings: Settings, manager: ClientManager, anthropic: AsyncAnthropic) -> AsyncApp:
    app = AsyncApp(token=settings.slack_bot_token)

    async def answer(user_id: str, text: str, say, thread_ts: str | None) -> None:
        text = MENTION_RE.sub("", text).strip()
        if not text:
            await say(text="Ask me something, e.g. `what's on my calendar today?`", thread_ts=thread_ts)
            return

        client = await get_user_client(manager, user_id)

        # A completed authorization can leave a stale auth-pending record
        # behind (the SDK clears it in a background task that may be
        # cancelled), so the live session state is the source of truth: a
        # server only needs auth when its session is not operational.
        pending = [
            challenge
            for challenge in await client.get_auth_challenges()
            if not _session_operational(client, challenge.get("server"))
        ]
        if pending:
            await say(text=_format_auth_prompt(pending), thread_ts=thread_ts)
            return

        if not any(session.is_operational for session in client.sessions.values()):
            await say(
                text="I couldn't reach any MCP server. Check the MCP_SERVERS URLs and the agent logs.",
                thread_ts=thread_ts,
            )
            return

        try:
            reply = await run_agent(anthropic, client, text)
        except Exception:
            logger.exception("Agent turn failed for user %s", user_id)
            reply = "Something went wrong on my end. Check the agent logs and try again."
        await say(text=reply, thread_ts=thread_ts)

    @app.event("app_mention")
    async def on_mention(event, say):
        thread_ts = event.get("thread_ts") or event["ts"]
        await answer(event["user"], event.get("text", ""), say, thread_ts)

    @app.event("message")
    async def on_message(event, say):
        # Only handle plain human DMs. Skip bot echoes, edits, and channel
        # messages (channel mentions arrive via app_mention above).
        if event.get("channel_type") != "im":
            return
        if event.get("bot_id") or event.get("subtype"):
            return
        await answer(event["user"], event.get("text", ""), say, thread_ts=None)

    return app
