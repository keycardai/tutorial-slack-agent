/**
 * Environment configuration.
 *
 * All settings come from environment variables. See .env.example for the
 * full table. The app exits with a readable error when required variables
 * are missing, so a bare `npm start` tells you exactly what to set.
 */

// Loads .env into process.env; values already present in the environment win.
import "dotenv/config";

export interface ServerEntry {
	/** Short name used as the tool prefix the model sees (google__list_events). */
	key: string;
	/** MCP server URL, usually ending in /mcp. */
	url: string;
}

export interface Settings {
	slackBotToken: string;
	slackAppToken: string;
	anthropicApiKey: string;
	mcpServers: ServerEntry[];
	port: number;
	baseUrl: string;
	tokenStorePath: string;
	oauthRedirectUri: string;
}

const REQUIRED_VARS = [
	"SLACK_BOT_TOKEN",
	"SLACK_APP_TOKEN",
	"ANTHROPIC_API_KEY",
	"MCP_SERVERS",
] as const;

function fail(message: string): never {
	console.error(message);
	process.exit(1);
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseServers(raw: string): ServerEntry[] {
	let entries: unknown;
	try {
		entries = JSON.parse(raw);
	} catch (error) {
		fail(
			"MCP_SERVERS is not valid JSON. Expected an array like:\n" +
				'  [{"key": "google", "url": "http://localhost:8000/mcp"}]\n' +
				"JSON needs double quotes around keys and values, with no " +
				"backslash escapes and no quotes around the whole value.\n" +
				`Received: ${raw}\n` +
				`Parse error: ${error instanceof Error ? error.message : String(error)}`,
		);
	}

	if (!Array.isArray(entries) || entries.length === 0) {
		fail("MCP_SERVERS must be a non-empty JSON array of {key, url} objects.");
	}

	const servers: ServerEntry[] = [];
	for (const entry of entries) {
		if (
			!isRecord(entry) ||
			typeof entry.key !== "string" ||
			entry.key === "" ||
			typeof entry.url !== "string" ||
			entry.url === ""
		) {
			fail(
				`Each MCP_SERVERS entry needs a 'key' and a 'url'. Bad entry: ${JSON.stringify(entry)}`,
			);
		}
		servers.push({ key: entry.key, url: entry.url });
	}
	return servers;
}

/** Read and validate settings from the environment. Exits on bad config. */
export function loadSettings(): Settings {
	const missing = REQUIRED_VARS.filter((name) => !process.env[name]);
	if (missing.length > 0) {
		fail(
			`Missing required environment variables: ${missing.join(", ")}\n` +
				"Copy .env.example to .env, fill in the values, then run:\n" +
				"  npm start",
		);
	}

	const port = Number.parseInt(process.env.PORT ?? "3000", 10);
	if (Number.isNaN(port)) {
		fail(`PORT must be a number, got: ${process.env.PORT}`);
	}
	const baseUrl = (process.env.BASE_URL ?? `http://localhost:${port}`).replace(/\/+$/, "");

	return {
		slackBotToken: process.env.SLACK_BOT_TOKEN ?? "",
		slackAppToken: process.env.SLACK_APP_TOKEN ?? "",
		anthropicApiKey: process.env.ANTHROPIC_API_KEY ?? "",
		mcpServers: parseServers(process.env.MCP_SERVERS ?? ""),
		port,
		baseUrl,
		tokenStorePath: process.env.TOKEN_STORE_PATH ?? "data/mcp-auth.json",
		oauthRedirectUri: `${baseUrl}/oauth/callback`,
	};
}
