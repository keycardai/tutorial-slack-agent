"""Conversation memory: replay the recent Slack thread to the model.

There is no conversation store. Slack already keeps the transcript, so
each turn re-reads the last few messages of the DM or channel thread and
hands them to Claude. Restarts lose nothing because nothing is held.
"""

from __future__ import annotations

import re
from typing import Any

from slack_sdk.web.async_client import AsyncWebClient

# The last N Slack messages ARE the memory. There is no store and no
# summarization by design; raise or lower this to trade tokens for recall.
HISTORY_LIMIT = 12

# Cap each replayed message so one giant paste cannot crowd out the rest
# of the context window.
MAX_MESSAGE_CHARS = 2000

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")


async def fetch_history(
    slack: AsyncWebClient, channel: str, thread_ts: str | None
) -> list[dict[str, Any]]:
    """Fetch the recent Slack conversation, oldest message first.

    Channel threads use conversations.replies, which is already oldest
    first. DMs use conversations.history, which is newest first, so the
    result is reversed.
    """
    if thread_ts:
        response = await slack.conversations_replies(
            channel=channel, ts=thread_ts, limit=HISTORY_LIMIT
        )
        return list(response.get("messages") or [])
    response = await slack.conversations_history(channel=channel, limit=HISTORY_LIMIT)
    return list(reversed(response.get("messages") or []))


def build_conversation(
    history: list[dict[str, Any]],
    current_text: str,
    bot_user_id: str | None,
    current_ts: str,
) -> list[dict[str, Any]]:
    """Convert Slack messages plus the current question into Anthropic messages.

    Pure function: Slack messages in, Anthropic messages out.
    """
    turns: list[dict[str, Any]] = []
    for message in history:
        # Joins, edits, and other system noise carry a subtype.
        if message.get("subtype"):
            continue
        # The triggering message is appended separately below.
        if message.get("ts") == current_ts:
            continue
        text = MENTION_RE.sub("", message.get("text") or "").strip()
        if not text:
            continue
        is_bot = bool(message.get("bot_id")) or message.get("user") == bot_user_id
        turns.append(
            {"role": "assistant" if is_bot else "user", "content": text[:MAX_MESSAGE_CHARS]}
        )

    turns.append({"role": "user", "content": current_text})

    # The Messages API requires the first message to have role "user" and
    # rejects consecutive same-role messages: drop leading assistant turns
    # and merge adjacent same-role turns.
    merged: list[dict[str, Any]] = []
    for turn in turns:
        if not merged and turn["role"] == "assistant":
            continue
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"] = f"{merged[-1]['content']}\n{turn['content']}"
        else:
            merged.append(turn)
    return merged
