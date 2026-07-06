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
import { runAgent } from "./agent.js";
import type { Settings } from "./config.js";
import { isReady, type McpManager, type ServerSession } from "./mcp.js";

const { App } = bolt;
export type SlackApp = InstanceType<typeof App>;

const MENTION_RE = /<@[A-Z0-9]+>/g;

type Say = (message: { text: string; thread_ts?: string }) => Promise<unknown>;

function formatAuthPrompt(challenges: ServerSession[]): string {
	const lines = [
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
	lines.push("When you're done, ask me again.");
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

	async function answer(
		userId: string,
		rawText: string,
		say: Say,
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

		let reply: string;
		try {
			reply = await runAgent(anthropic, ready, text);
		} catch (error) {
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
		await answer(event.user, event.text ?? "", say, threadTs);
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
		await answer(event.user, event.text ?? "", say, undefined);
	});

	return app;
}
