/**
 * Process entry point.
 *
 * Runs two things side by side in one Node process:
 *
 * - an Express app on PORT. Its only real route is /oauth/callback, the
 *   OAuth redirect target for MCP authorization. For local runs the
 *   user's browser hits http://localhost:PORT directly, so no tunnel is
 *   needed.
 * - Bolt's Socket Mode connection, which keeps a websocket open to Slack
 *   so the bot needs no public URL for events either.
 */

import Anthropic from "@anthropic-ai/sdk";
import express from "express";
import { buildApp } from "./bot.js";
import { loadSettings } from "./config.js";
import { McpManager } from "./mcp.js";
import { FileAuthStore } from "./storage.js";

function htmlPage(title: string, body: string): string {
	return `<!doctype html>
<html>
<head><meta charset="utf-8"><title>${title}</title></head>
<body style="font-family: sans-serif; max-width: 32rem; margin: 4rem auto;">
<h1>${title}</h1>
<p>${body}</p>
</body>
</html>`;
}

async function main(): Promise<void> {
	const settings = loadSettings();

	const store = new FileAuthStore(settings.tokenStorePath);
	const manager = new McpManager(settings.mcpServers, store, settings.oauthRedirectUri);
	const anthropic = new Anthropic({ apiKey: settings.anthropicApiKey });
	const app = buildApp(settings, manager, anthropic);

	const web = express();

	web.get("/healthz", (_req, res) => {
		res.json({ ok: true });
	});

	web.get("/oauth/callback", (req, res) => {
		void (async () => {
			const code = typeof req.query.code === "string" ? req.query.code : undefined;
			const state = typeof req.query.state === "string" ? req.query.state : undefined;
			const oauthError = typeof req.query.error === "string" ? req.query.error : undefined;

			if (oauthError || !code || !state) {
				res
					.status(400)
					.send(
						htmlPage(
							"Authorization failed",
							oauthError
								? `Keycard reported: ${oauthError}. Ask the bot again for a fresh link.`
								: "Missing code or state in the callback. Ask the bot again for a fresh link.",
						),
					);
				return;
			}

			try {
				const { userId, serverKey } = await manager.completeAuthorization(state, code);
				// Best-effort DM; the browser page already confirms success.
				try {
					await app.client.chat.postMessage({
						channel: userId,
						text: `:white_check_mark: Connected to *${serverKey}*. Ask me your question again!`,
					});
				} catch (error) {
					console.error(`Failed to send auth-complete DM to ${userId}:`, error);
				}
				res.send(
					htmlPage("Connected!", "You can close this tab and go back to Slack."),
				);
			} catch (error) {
				console.error("OAuth callback failed:", error);
				res
					.status(400)
					.send(
						htmlPage(
							"Authorization failed",
							"This link may have expired (authorization links are one-time). " +
								"Ask the bot again to get a fresh one.",
						),
					);
			}
		})();
	});

	await new Promise<void>((resolve) => {
		web.listen(settings.port, "0.0.0.0", () => resolve());
	});
	console.log(
		`OAuth callback listening at ${settings.oauthRedirectUri}, ` +
			`MCP servers: ${settings.mcpServers.map((entry) => entry.key).join(", ")}`,
	);

	try {
		await app.init();
		await app.start();
		console.log("Slack Socket Mode connected.");
	} catch (error) {
		// Keep the callback server alive so in-flight authorizations can
		// still land, but make the Slack failure loud.
		console.error(
			"Failed to connect to Slack (check SLACK_BOT_TOKEN and SLACK_APP_TOKEN):",
			error instanceof Error ? error.message : error,
		);
		await app.stop().catch(() => {});
	}
}

main().catch((error: unknown) => {
	console.error("Fatal:", error);
	process.exit(1);
});
