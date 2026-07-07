/**
 * Conversation memory: replay the recent Slack thread to the model.
 *
 * There is no conversation store. Slack already keeps the transcript, so
 * each turn re-reads the last few messages of the DM or channel thread
 * and hands them to Claude. Restarts lose nothing because nothing is held.
 */

import type Anthropic from "@anthropic-ai/sdk";
import type { WebClient } from "@slack/web-api";

// The last N Slack messages ARE the memory. There is no store and no
// summarization by design; raise or lower this to trade tokens for recall.
export const HISTORY_LIMIT = 12;

// Cap each replayed message so one giant paste cannot crowd out the rest
// of the context window.
const MAX_MESSAGE_CHARS = 2000;

const MENTION_RE = /<@[A-Z0-9]+>/g;

/** The subset of a Slack message the converter cares about. */
export interface SlackHistoryMessage {
	ts?: string;
	text?: string;
	user?: string;
	bot_id?: string;
	subtype?: string;
}

/**
 * Fetch the recent Slack conversation, oldest message first.
 *
 * Channel threads use conversations.replies, which is already oldest
 * first. DMs use conversations.history, which is newest first, so the
 * result is reversed.
 */
export async function fetchHistory(
	slack: WebClient,
	channel: string,
	threadTs: string | undefined,
): Promise<SlackHistoryMessage[]> {
	if (threadTs) {
		const response = await slack.conversations.replies({
			channel,
			ts: threadTs,
			limit: HISTORY_LIMIT,
		});
		return response.messages ?? [];
	}
	const response = await slack.conversations.history({ channel, limit: HISTORY_LIMIT });
	return [...(response.messages ?? [])].reverse();
}

/**
 * Convert Slack messages plus the current question into Anthropic messages.
 *
 * Pure function: Slack messages in, Anthropic messages out.
 */
export function buildConversation(
	history: SlackHistoryMessage[],
	currentText: string,
	botUserId: string | undefined,
	currentTs: string,
): Anthropic.Messages.MessageParam[] {
	const turns: { role: "user" | "assistant"; content: string }[] = [];
	for (const message of history) {
		// Joins, edits, and other system noise carry a subtype.
		if (message.subtype) {
			continue;
		}
		// The triggering message is appended separately below.
		if (message.ts === currentTs) {
			continue;
		}
		const text = (message.text ?? "").replace(MENTION_RE, "").trim();
		if (!text) {
			continue;
		}
		const isBot = Boolean(message.bot_id) || message.user === botUserId;
		turns.push({
			role: isBot ? "assistant" : "user",
			content: text.slice(0, MAX_MESSAGE_CHARS),
		});
	}

	turns.push({ role: "user", content: currentText });

	// The Messages API requires the first message to have role "user" and
	// rejects consecutive same-role messages: drop leading assistant turns
	// and merge adjacent same-role turns.
	const merged: { role: "user" | "assistant"; content: string }[] = [];
	for (const turn of turns) {
		const last = merged[merged.length - 1];
		if (!last && turn.role === "assistant") {
			continue;
		}
		if (last && last.role === turn.role) {
			last.content = `${last.content}\n${turn.content}`;
		} else {
			merged.push(turn);
		}
	}
	return merged;
}
