/**
 * Slack ingress: a Bolt App running in Socket Mode.
 *
 * Two entry points, both funneled into one handler:
 *
 * - @mentions in channels (app_mention events), replied to in-thread
 * - direct messages (message.im events), replied to in the DM
 *
 * Auth UX: if any MCP server needs OAuth for this user, we post the
 * authorization link(s) instead of answering. After the user authorizes
 * in the browser, the callback route in main.ts DMs them to try again.
 * Simple and stateless: no automatic resume of the original question.
 */

import type Anthropic from "@anthropic-ai/sdk";
import bolt from "@slack/bolt";
import { ReauthRequired, runAgent } from "./agent.js";
import type { Settings } from "./config.js";
import { buildConversation, fetchHistory } from "./history.js";
import { isReady, type McpManager, type ServerSession } from "./mcp.js";

const { App } = bolt;
export type SlackApp = InstanceType<typeof App>;

const MENTION_RE = /<@[A-Z0-9]+>/g;

type Say = (message: { text: string; thread_ts?: string }) => Promise<unknown>;

function formatAuthPrompt(challenges: ServerSession[], intro?: string): string {
	const lines = [
		intro ??
			"Before I can help, you need to connect your account(s). " +
				"Click to authorize (the link is personal to you):",
	];
	for (const challenge of challenges) {
		if (challenge.authorizationUrl) {
			lines.push(`• <${challenge.authorizationUrl.toString()}|Connect ${challenge.serverKey}>`);
		} else {
			lines.push(`• ${challenge.serverKey}: authorization required but no URL was issued`);
		}
	}
	lines.push("Use this newest link (older ones expire), then ask me again.");
	return lines.join("\n");
}

export function buildApp(
	settings: Settings,
	manager: McpManager,
	anthropic: Anthropic,
): SlackApp {
	const app = new App({
		token: settings.slackBotToken,
		appToken: settings.slackAppToken,
		socketMode: true,
		// Without this, Bolt's constructor fires an auth.test whose promise
		// nothing handles; a bad token would then crash the whole process
		// instead of surfacing where main() awaits app.init().
		deferInitialization: true,
	});

	// The bot's own user id distinguishes its messages in fetched history.
	// Resolved lazily via auth.test on the first turn, then cached.
	let botUserId: string | undefined;

	async function getBotUserId(): Promise<string | undefined> {
		if (!botUserId) {
			const auth = await app.client.auth.test();
			botUserId = auth.user_id;
		}
		return botUserId;
	}

	async function answer(
		userId: string,
		rawText: string,
		say: Say,
		channel: string,
		ts: string,
		threadTs: string | undefined,
	): Promise<void> {
		const text = rawText.replace(MENTION_RE, "").trim();
		if (!text) {
			await say({
				text: "Ask me something, e.g. `what's on my calendar today?`",
				thread_ts: threadTs,
			});
			return;
		}

		const sessions = await manager.connectUser(userId);

		const challenges = sessions.filter((session) => session.status === "needs-auth");
		if (challenges.length > 0) {
			await say({ text: formatAuthPrompt(challenges), thread_ts: threadTs });
			return;
		}

		const ready = sessions.filter(isReady);
		if (ready.length === 0) {
			await say({
				text: "I couldn't reach any MCP server. Check the MCP_SERVERS URLs and the agent logs.",
				thread_ts: threadTs,
			});
			return;
		}

		// Memory is just the recent Slack conversation replayed to the model.
		// If Slack won't give it to us (missing scope, rate limit), answer
		// from the current message alone rather than failing the turn.
		let messages: Anthropic.Messages.MessageParam[];
		try {
			const history = await fetchHistory(app.client, channel, threadTs);
			messages = buildConversation(history, text, await getBotUserId(), ts);
		} catch (error) {
			console.info("History fetch failed, answering without context:", error);
			messages = [{ role: "user", content: text }];
		}

		let reply: string;
		try {
			reply = await runAgent(anthropic, ready, messages);
		} catch (error) {
			if (error instanceof ReauthRequired) {
				// A tool failed because the grant was revoked/expired upstream.
				// Clear the stale token and post a fresh authorization link so
				// the user can reconnect without us wiping the token store.
				console.info(`Re-auth required for ${error.serverKey} (user ${userId})`);
				let session: ServerSession | undefined;
				try {
					session = await manager.forceReauth(userId, error.serverKey);
				} catch (reauthError) {
					console.error(`forceReauth failed for ${error.serverKey} (user ${userId}):`, reauthError);
				}
				if (session && session.status === "needs-auth") {
					await say({
						text: formatAuthPrompt(
							[session],
							`Your access to *${error.serverKey}* was revoked or expired. ` +
								"Reconnect to keep going:",
						),
						thread_ts: threadTs,
					});
				} else {
					await say({
						text:
							`Your access to ${error.serverKey} needs reconnecting, but I ` +
							"couldn't start the flow. Check the agent logs and try again.",
						thread_ts: threadTs,
					});
				}
				return;
			}
			console.error(`Agent turn failed for user ${userId}:`, error);
			reply = "Something went wrong on my end. Check the agent logs and try again.";
		}
		await say({ text: reply, thread_ts: threadTs });
	}

	app.event("app_mention", async ({ event, say }) => {
		if (!event.user) {
			return;
		}
		const threadTs = event.thread_ts ?? event.ts;
		await answer(event.user, event.text ?? "", say, event.channel, event.ts, threadTs);
	});

	app.event("message", async ({ event, say }) => {
		// Only handle plain human DMs. Skip bot echoes, edits, and channel
		// messages (channel mentions arrive via app_mention above).
		if (event.channel_type !== "im" || event.subtype !== undefined) {
			return;
		}
		if ("bot_id" in event && event.bot_id) {
			return;
		}
		await answer(event.user, event.text ?? "", say, event.channel, event.ts, undefined);
	});

	return app;
}
