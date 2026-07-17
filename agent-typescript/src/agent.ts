/**
 * A deliberately small Anthropic tool loop.
 *
 * Flow per Slack message:
 *
 * 1. List the tools available on the user's MCP sessions and convert them
 *    to Anthropic tool definitions (namespaced "<server>__<tool>" so two
 *    servers can expose tools with the same name).
 * 2. Call the model. If it wants tools, execute them through the user's
 *    MCP clients, append the results, and loop.
 * 3. Stop when the model answers in plain text or the iteration cap is hit.
 *
 * No streaming, no persona, no conversation store. Memory is the recent
 * Slack thread, fetched by the caller and passed in as the message list.
 */

import type Anthropic from "@anthropic-ai/sdk";
import type { ReadySession } from "./mcp.js";

const MODEL = "claude-sonnet-4-6";
const MAX_TOKENS = 4096;
const MAX_ITERATIONS = 10;

const SYSTEM_PROMPT = `You are a helpful assistant living in Slack. Answer concisely in Slack style:
plain text, short paragraphs, no markdown headers.

You have tools from one or more MCP servers. Tool names are prefixed with the
server they come from (for example google__list_events). Use them whenever the
user's question needs live data, and answer from the results.

Today's date (UTC): {today}
`;

interface ToolRoute {
	session: ReadySession;
	toolName: string;
}

/**
 * Thrown when a tool fails because the user's authorization is no longer
 * valid. Revoking a grant in Keycard (or an expired upstream grant) kills the
 * delegated token exchange the MCP server does at call time, while the
 * client's own session to the MCP server stays connected — so no 401 fires
 * and the only signal is the failure inside the tool result. The bot catches
 * this to re-run the OAuth flow for the named server.
 */
export class ReauthRequired extends Error {
	constructor(readonly serverKey: string) {
		super(`Re-authorization required for ${serverKey}`);
		this.name = "ReauthRequired";
	}
}

// The exact prefix the Google MCP server returns in the "error" field when the
// delegated grant is missing/revoked/expired. Anchor on the structured error
// field, not the rendered text: the server this tutorial ships is Google
// (Gmail/Calendar/Drive/Docs), where auth-ish strings are ordinary content —
// a security-alert email, a doc titled "authentication errors runbook" — and
// must not be mistaken for a real auth failure.
const AUTH_ERROR_PREFIX = "Authentication errors:";

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * True only for the structured auth-failure shape the MCP tools return.
 *
 * The Google tools return failures as { success: false, error, isError: true };
 * a revoked/expired grant sets "error" to the "Authentication errors: ..."
 * message. Ordinary API errors set a different message, and successful results
 * have no top-level "error", so this never fires on real content or on
 * unrelated tool errors.
 */
function isAuthFailure(structured: unknown): boolean {
	if (!isRecord(structured)) {
		return false;
	}
	const error = structured.error;
	return typeof error === "string" && error.startsWith(AUTH_ERROR_PREFIX);
}

/**
 * Convert MCP tools to Anthropic tool definitions, plus a routing map from
 * the namespaced Anthropic tool name back to (session, mcp tool name).
 */
async function collectTools(
	sessions: ReadySession[],
): Promise<{ definitions: Anthropic.Messages.Tool[]; routes: Map<string, ToolRoute> }> {
	const definitions: Anthropic.Messages.Tool[] = [];
	const routes = new Map<string, ToolRoute>();

	for (const session of sessions) {
		let cursor: string | undefined;
		do {
			const page = await session.client.listTools({ cursor });
			for (const tool of page.tools) {
				const name = `${session.serverKey}__${tool.name}`.slice(0, 128);
				routes.set(name, { session, toolName: tool.name });
				definitions.push({
					name,
					description: tool.description ?? tool.name,
					input_schema: tool.inputSchema ?? { type: "object", properties: {} },
				});
			}
			cursor = page.nextCursor;
		} while (cursor);
	}
	return { definitions, routes };
}

/**
 * Run one MCP tool call. Returns the text result, an error flag, and the
 * tool's structured content (the dict the Google tools produce) when present —
 * used to detect an auth failure at the boundary instead of string-matching
 * the rendered text.
 */
async function executeTool(
	route: ToolRoute,
	args: Record<string, unknown>,
): Promise<{ text: string; isError: boolean; structured: unknown }> {
	const { session, toolName } = route;
	let result: Awaited<ReturnType<typeof session.client.callTool>>;
	try {
		result = await session.client.callTool({ name: toolName, arguments: args });
	} catch (error) {
		console.error(`MCP tool call failed: ${session.serverKey}/${toolName}`, error);
		const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
		return {
			text: `Error calling ${session.serverKey}/${toolName}: ${detail}`,
			isError: true,
			structured: undefined,
		};
	}

	const content: unknown = result.content;
	const parts: string[] = [];
	if (Array.isArray(content)) {
		for (const block of content) {
			if (isRecord(block) && typeof block.text === "string") {
				parts.push(block.text);
			}
		}
	}
	return {
		text: parts.length > 0 ? parts.join("\n") : "(empty result)",
		isError: result.isError === true,
		structured: result.structuredContent,
	};
}

/**
 * Answer the latest user message, executing MCP tools as needed.
 *
 * The caller supplies the conversation so far (recent Slack history plus
 * the current question, ending with a user message). The tool loop
 * appends tool_use and tool_result turns to that same list.
 */
export async function runAgent(
	anthropic: Anthropic,
	sessions: ReadySession[],
	messages: Anthropic.Messages.MessageParam[],
): Promise<string> {
	const { definitions, routes } = await collectTools(sessions);
	const today = new Date().toISOString().slice(0, 10);
	const weekday = new Date().toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
	const system = SYSTEM_PROMPT.replace("{today}", `${weekday}, ${today}`);

	for (let iteration = 0; iteration < MAX_ITERATIONS; iteration++) {
		const response = await anthropic.messages.create({
			model: MODEL,
			max_tokens: MAX_TOKENS,
			system,
			tools: definitions,
			messages,
		});

		if (response.stop_reason !== "tool_use") {
			const text = response.content
				.filter((block) => block.type === "text")
				.map((block) => block.text)
				.join("")
				.trim();
			return text || "(no response)";
		}

		messages.push({ role: "assistant", content: response.content });

		const toolResults: Anthropic.Messages.ToolResultBlockParam[] = [];
		for (const block of response.content) {
			if (block.type !== "tool_use") {
				continue;
			}
			const route = routes.get(block.name);
			if (!route) {
				toolResults.push({
					type: "tool_result",
					tool_use_id: block.id,
					content: `Unknown tool: ${block.name}`,
					is_error: true,
				});
				continue;
			}
			console.log(`tool call: ${route.session.serverKey}/${route.toolName}`);
			const args = isRecord(block.input) ? block.input : {};
			const { text, isError, structured } = await executeTool(route, args);
			// A revoked/expired grant comes back as a structured error (the tool
			// returns a dict, so isError stays false). Detect that specific
			// shape and let the bot re-run OAuth rather than feeding the model
			// an auth error it can't recover from.
			if (isAuthFailure(structured)) {
				throw new ReauthRequired(route.session.serverKey);
			}
			toolResults.push({
				type: "tool_result",
				tool_use_id: block.id,
				content: text,
				is_error: isError,
			});
		}
		messages.push({ role: "user", content: toolResults });
	}

	return "I hit my tool-call limit answering that. Try asking something narrower.";
}
