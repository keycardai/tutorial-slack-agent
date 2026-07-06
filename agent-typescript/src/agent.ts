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
 * No streaming, no memory, no persona. That is the point of this repo.
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

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
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

/** Run one MCP tool call. Returns the text result and an error flag. */
async function executeTool(
	route: ToolRoute,
	args: Record<string, unknown>,
): Promise<{ text: string; isError: boolean }> {
	const { session, toolName } = route;
	let result: Awaited<ReturnType<typeof session.client.callTool>>;
	try {
		result = await session.client.callTool({ name: toolName, arguments: args });
	} catch (error) {
		console.error(`MCP tool call failed: ${session.serverKey}/${toolName}`, error);
		const detail = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
		return { text: `Error calling ${session.serverKey}/${toolName}: ${detail}`, isError: true };
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
	};
}

/** Answer one user message, executing MCP tools as needed. */
export async function runAgent(
	anthropic: Anthropic,
	sessions: ReadySession[],
	userText: string,
): Promise<string> {
	const { definitions, routes } = await collectTools(sessions);
	const today = new Date().toISOString().slice(0, 10);
	const weekday = new Date().toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
	const system = SYSTEM_PROMPT.replace("{today}", `${weekday}, ${today}`);

	const messages: Anthropic.Messages.MessageParam[] = [{ role: "user", content: userText }];

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
			const { text, isError } = await executeTool(route, args);
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
