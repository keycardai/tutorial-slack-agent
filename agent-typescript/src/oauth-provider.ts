/**
 * The Keycard piece: one OAuth client provider per (Slack user, MCP server).
 *
 * We build on BaseOAuthClientProvider from @keycardai/mcp, which implements
 * the MCP SDK's OAuthClientProvider interface and accepts pluggable token
 * and code-verifier stores. This subclass adds the three things a
 * multi-user Slack agent needs on top:
 *
 * - Dynamic Client Registration (RFC 7591): the base class only knows a
 *   static clientId, so we persist the registration the MCP SDK obtains
 *   from Keycard (clientInformation / saveClientInformation).
 * - Browser-less redirect: redirectToAuthorization cannot open a browser
 *   from a bot process, so it hands the authorization URL to an injected
 *   callback that posts it into Slack.
 * - Routable state: the OAuth state parameter is issued by the manager so
 *   the /oauth/callback route can map it back to (user, server).
 */

import { BaseOAuthClientProvider } from "@keycardai/mcp/client/auth/providers/base";
import type {
	OAuthClientInformationFull,
	OAuthClientMetadata,
} from "@modelcontextprotocol/sdk/shared/auth.js";
import type { FileAuthStore } from "./storage.js";

export interface AuthFlowHooks {
	/**
	 * Return the OAuth state parameter for a new authorization. The manager
	 * remembers it so the callback route can resolve it back to this
	 * (user, server) pair.
	 */
	issueState(): string;
	/** Receive the Keycard authorization URL the user must open. */
	onAuthorizationUrl(url: URL): void | Promise<void>;
}

export class SlackUserOAuthProvider extends BaseOAuthClientProvider {
	constructor(
		private readonly userId: string,
		private readonly serverKey: string,
		private readonly store: FileAuthStore,
		redirectUrl: string,
		private readonly hooks: AuthFlowHooks,
	) {
		const metadata: OAuthClientMetadata = {
			client_name: "tutorial-slack-agent",
			redirect_uris: [redirectUrl],
			grant_types: ["authorization_code", "refresh_token"],
			response_types: ["code"],
			// Public client: no secret, PKCE proves possession of the flow.
			token_endpoint_auth_method: "none",
		};
		super(metadata, undefined, {
			redirectUrl,
			tokensStore: {
				get: async () => store.getTokens(userId, serverKey),
				save: (tokens) => store.saveTokens(userId, serverKey, tokens),
			},
			codeVerifierStore: {
				get: () => {
					const verifier = store.getCodeVerifier(userId, serverKey);
					if (!verifier) {
						throw new Error(
							`No PKCE code verifier stored for ${userId}/${serverKey}. ` +
								"The authorization link may be stale; ask the bot again.",
						);
					}
					return verifier;
				},
				save: (verifier) => store.saveCodeVerifier(userId, serverKey, verifier),
			},
		});
	}

	/**
	 * The base class derives client information from a static clientId.
	 * We return the Dynamic Client Registration record instead, persisted
	 * by saveClientInformation below.
	 */
	override clientInformation(): OAuthClientInformationFull | undefined {
		return this.store.getClientInformation(this.userId, this.serverKey);
	}

	/**
	 * Declaring this optional OAuthClientProvider method is what tells the
	 * MCP SDK it may register the client dynamically with Keycard.
	 */
	saveClientInformation(clientInformation: OAuthClientInformationFull): void {
		this.store.saveClientInformation(this.userId, this.serverKey, clientInformation);
	}

	/** The MCP SDK calls this (if present) to supply the OAuth state parameter. */
	state(): string {
		return this.hooks.issueState();
	}

	override async redirectToAuthorization(authorizationUrl: URL): Promise<void> {
		await this.hooks.onAuthorizationUrl(authorizationUrl);
	}
}
