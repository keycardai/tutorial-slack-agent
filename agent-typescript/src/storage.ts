/**
 * A single JSON file holding all per-user OAuth state: tokens, PKCE code
 * verifiers, and Dynamic Client Registration records, keyed by
 * "<slackUserId>::<serverKey>".
 *
 * Writes are synchronous and atomic (write a temp file, then rename).
 * Synchronous matters here: BaseOAuthClientProvider calls the store's
 * save() without awaiting it, so an async write could lose a race with
 * the next read. A tutorial-grade trade-off; a real deployment would use
 * a database. To force everyone to re-authorize, delete the file.
 */

import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type {
	OAuthClientInformationFull,
	OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";

interface AuthRecord {
	tokens?: OAuthTokens;
	codeVerifier?: string;
	clientInformation?: OAuthClientInformationFull;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

export class FileAuthStore {
	constructor(private readonly path: string) {}

	getTokens(userId: string, serverKey: string): OAuthTokens | undefined {
		return this.record(userId, serverKey).tokens;
	}

	saveTokens(userId: string, serverKey: string, tokens: OAuthTokens): void {
		this.update(userId, serverKey, { tokens });
	}

	/**
	 * Delete just this user/server's tokens, keeping the DCR client
	 * registration so the next connect reuses it. Returns whether a token was
	 * actually removed — false means nothing was stored, so a caller forcing
	 * re-auth would get no 401 and should say so rather than claim recovery.
	 */
	clearTokens(userId: string, serverKey: string): boolean {
		const all = this.readAll();
		const key = this.key(userId, serverKey);
		const existing = isRecord(all[key]) ? (all[key] as AuthRecord) : undefined;
		if (!existing || existing.tokens === undefined) {
			return false;
		}
		const next: AuthRecord = { ...existing };
		delete next.tokens;
		all[key] = next;
		this.writeAll(all);
		return true;
	}

	getCodeVerifier(userId: string, serverKey: string): string | undefined {
		return this.record(userId, serverKey).codeVerifier;
	}

	saveCodeVerifier(userId: string, serverKey: string, codeVerifier: string): void {
		this.update(userId, serverKey, { codeVerifier });
	}

	getClientInformation(
		userId: string,
		serverKey: string,
	): OAuthClientInformationFull | undefined {
		return this.record(userId, serverKey).clientInformation;
	}

	saveClientInformation(
		userId: string,
		serverKey: string,
		clientInformation: OAuthClientInformationFull,
	): void {
		this.update(userId, serverKey, { clientInformation });
	}

	private key(userId: string, serverKey: string): string {
		return `${userId}::${serverKey}`;
	}

	private record(userId: string, serverKey: string): AuthRecord {
		const value = this.readAll()[this.key(userId, serverKey)];
		return isRecord(value) ? (value as AuthRecord) : {};
	}

	private update(userId: string, serverKey: string, patch: AuthRecord): void {
		const all = this.readAll();
		const key = this.key(userId, serverKey);
		const existing = isRecord(all[key]) ? (all[key] as AuthRecord) : {};
		all[key] = { ...existing, ...patch };
		this.writeAll(all);
	}

	private readAll(): Record<string, unknown> {
		let raw: string;
		try {
			raw = readFileSync(this.path, "utf8");
		} catch {
			return {};
		}
		try {
			const parsed: unknown = JSON.parse(raw);
			return isRecord(parsed) ? parsed : {};
		} catch {
			console.warn(`Auth store at ${this.path} is not valid JSON; starting fresh.`);
			return {};
		}
	}

	private writeAll(all: Record<string, unknown>): void {
		mkdirSync(dirname(this.path), { recursive: true });
		const tmp = `${this.path}.tmp`;
		writeFileSync(tmp, `${JSON.stringify(all, null, "\t")}\n`, "utf8");
		renameSync(tmp, this.path);
	}
}
