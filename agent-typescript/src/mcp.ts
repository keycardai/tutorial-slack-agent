/**
 * MCP wiring: one Client per (Slack user, MCP server).
 *
 * connectUser() never throws for ordinary failures. Servers that answer
 * 401 move to "needs-auth" and carry the Keycard authorization URL the
 * MCP SDK produced (discovery per RFC 9728, Dynamic Client Registration
 * per RFC 7591, then the PKCE authorization request). The bot posts that
 * link; when the user's browser comes back to /oauth/callback,
 * completeAuthorization() exchanges the code and reconnects.
 */

import { randomBytes } from "node:crypto";
import { UnauthorizedError } from "@modelcontextprotocol/sdk/client/auth.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import type { ServerEntry } from "./config.js";
import { SlackUserOAuthProvider } from "./oauth-provider.js";
import type { FileAuthStore } from "./storage.js";

export type SessionStatus = "ready" | "needs-auth" | "failed";

export interface ServerSession {
	serverKey: string;
	serverUrl: string;
	status: SessionStatus;
	client: Client | undefined;
	/** Present when status is "needs-auth". */
	authorizationUrl: URL | undefined;
}

export type ReadySession = ServerSession & { client: Client };

export function isReady(session: ServerSession): session is ReadySession {
	return session.status === "ready" && session.client !== undefined;
}

interface PendingAuthorization {
	userId: string;
	serverKey: string;
}

export class McpManager {
	private readonly sessionsByUser = new Map<string, Map<string, ServerSession>>();
	/** OAuth state parameter -> who started the flow. One-time use. */
	private readonly pendingStates = new Map<string, PendingAuthorization>();

	constructor(
		private readonly servers: ServerEntry[],
		private readonly store: FileAuthStore,
		private readonly redirectUri: string,
	) {}

	/**
	 * Get (or create) this user's sessions, connecting any that are not
	 * ready yet. Repeat calls are cheap: ready sessions are left alone.
	 */
	async connectUser(userId: string): Promise<ServerSession[]> {
		let sessions = this.sessionsByUser.get(userId);
		if (!sessions) {
			sessions = new Map();
			this.sessionsByUser.set(userId, sessions);
		}
		for (const server of this.servers) {
			const existing = sessions.get(server.key);
			if (existing && isReady(existing)) {
				continue;
			}
			sessions.set(server.key, await this.connectServer(userId, server));
		}
		return [...sessions.values()];
	}

	/**
	 * Handle the browser hitting /oauth/callback. Resolves the state back
	 * to (user, server), exchanges the authorization code for tokens via
	 * the MCP SDK (transport.finishAuth), and reconnects the session.
	 */
	async completeAuthorization(
		state: string,
		code: string,
	): Promise<PendingAuthorization> {
		const pending = this.pendingStates.get(state);
		if (!pending) {
			throw new Error("Unknown or expired authorization state.");
		}
		this.pendingStates.delete(state);

		const server = this.servers.find((entry) => entry.key === pending.serverKey);
		if (!server) {
			throw new Error(`No configured MCP server named ${pending.serverKey}.`);
		}

		// finishAuth only performs the token exchange; the provider already
		// holds the client registration and PKCE verifier in the file store,
		// so a fresh transport works. Tokens are persisted by the provider.
		const provider = this.buildProvider(pending.userId, server, () => {});
		const transport = new StreamableHTTPClientTransport(new URL(server.url), {
			authProvider: provider,
		});
		await transport.finishAuth(code);

		const session = await this.connectServer(pending.userId, server);
		let sessions = this.sessionsByUser.get(pending.userId);
		if (!sessions) {
			sessions = new Map();
			this.sessionsByUser.set(pending.userId, sessions);
		}
		sessions.set(server.key, session);

		if (!isReady(session)) {
			throw new Error(
				`Authorized ${server.key}, but reconnecting failed (status: ${session.status}).`,
			);
		}
		return pending;
	}

	/**
	 * Drop a stale token and re-run the OAuth flow for one server.
	 *
	 * Called when a tool fails because the user's grant was revoked or expired
	 * upstream. The catch is that the session to the MCP server is still
	 * healthy (its own token is valid), so it never re-challenges on its own —
	 * only the delegated token exchange the MCP server does at call time fails.
	 *
	 * We delete just this server's stored token (keeping the DCR registration)
	 * so the next connect gets a fresh 401 -> authorization flow, which
	 * re-consents the revoked grant. Returns the reconnected session; when it
	 * comes back "needs-auth" it carries the fresh authorization URL to post.
	 */
	async forceReauth(userId: string, serverKey: string): Promise<ServerSession> {
		const server = this.servers.find((entry) => entry.key === serverKey);
		if (!server) {
			throw new Error(`No configured MCP server named ${serverKey}.`);
		}

		if (this.store.clearTokens(userId, serverKey)) {
			console.log(`Cleared stored token for ${userId}/${serverKey}; forcing re-auth`);
		} else {
			// No token to clear means the next connect won't get a 401 and we'd
			// post a "reconnect" link that cleared nothing. Surface it instead
			// of silently claiming recovery.
			console.warn(`forceReauth: no stored token found for ${userId}/${serverKey}`);
		}

		const session = await this.connectServer(userId, server);
		let sessions = this.sessionsByUser.get(userId);
		if (!sessions) {
			sessions = new Map();
			this.sessionsByUser.set(userId, sessions);
		}
		sessions.set(serverKey, session);
		return session;
	}

	private buildProvider(
		userId: string,
		server: ServerEntry,
		onAuthorizationUrl: (url: URL) => void,
	): SlackUserOAuthProvider {
		return new SlackUserOAuthProvider(userId, server.key, this.store, this.redirectUri, {
			issueState: () => {
				const state = randomBytes(24).toString("base64url");
				this.pendingStates.set(state, { userId, serverKey: server.key });
				return state;
			},
			onAuthorizationUrl,
		});
	}

	private async connectServer(
		userId: string,
		server: ServerEntry,
	): Promise<ServerSession> {
		const authUrlBox: { url: URL | undefined } = { url: undefined };
		const provider = this.buildProvider(userId, server, (url) => {
			authUrlBox.url = url;
		});
		const client = new Client({ name: "tutorial-slack-agent", version: "0.1.0" });
		const transport = new StreamableHTTPClientTransport(new URL(server.url), {
			authProvider: provider,
		});

		const session: ServerSession = {
			serverKey: server.key,
			serverUrl: server.url,
			status: "failed",
			client: undefined,
			authorizationUrl: undefined,
		};

		try {
			// If the server answers 401, the MCP SDK runs the full pre-auth
			// flow inside connect(): discovery, DCR, PKCE, and a call to our
			// provider's redirectToAuthorization, then throws UnauthorizedError.
			await client.connect(transport);
			session.status = "ready";
			session.client = client;
		} catch (error) {
			await transport.close().catch(() => {});
			if (error instanceof UnauthorizedError) {
				session.status = "needs-auth";
				session.authorizationUrl = authUrlBox.url;
			} else {
				console.error(
					`Failed to connect to MCP server ${server.key} (${server.url}):`,
					error instanceof Error ? error.message : error,
				);
			}
		}
		return session;
	}
}
