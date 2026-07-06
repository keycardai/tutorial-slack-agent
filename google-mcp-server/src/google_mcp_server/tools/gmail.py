"""Gmail Tools.

Tools for Gmail: search_emails, read_email, send_email, create_draft,
get_thread, list_labels, modify_message, trash_message.
"""

import asyncio
import base64
from email.message import EmailMessage
from typing import Any

from fastmcp import FastMCP, Context

from ..auth import auth_provider, get_google_token, GOOGLE_API_URL
from ..client import GoogleClientError, request, GOOGLE_GMAIL_API_URL


def _extract_header(headers: list[dict[str, str]], name: str) -> str | None:
    """Extract a header value from Gmail message headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def _extract_email_body(payload: dict[str, Any]) -> str:
    """Recursively extract text body from Gmail message payload.

    Handles multipart MIME bodies by recursing into parts.
    Prefers text/plain over text/html.
    """
    mime_type = payload.get("mimeType", "")

    # Simple part with data
    body_data = payload.get("body", {}).get("data")
    if body_data:
        decoded = base64.urlsafe_b64decode(body_data + "==").decode(
            "utf-8", errors="replace"
        )
        if mime_type in ("text/plain", "text/html"):
            return decoded

    # Multipart — recurse into parts
    parts = payload.get("parts", [])
    plain_text = ""
    html_text = ""
    for part in parts:
        part_mime = part.get("mimeType", "")
        extracted = _extract_email_body(part)
        if not extracted:
            continue
        if part_mime == "text/plain" and not plain_text:
            plain_text = extracted
        elif part_mime == "text/html" and not html_text:
            html_text = extracted
        elif part_mime.startswith("multipart/") and not plain_text:
            plain_text = extracted

    return plain_text or html_text


def _build_raw_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> str:
    """Build RFC 2822 message and return base64url-encoded."""
    msg = EmailMessage()
    msg.set_content(body)
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _parse_message_metadata(
    data: dict[str, Any],
) -> dict[str, Any]:
    """Extract common metadata fields from a Gmail message response."""
    headers = data.get("payload", {}).get("headers", [])
    return {
        "id": data.get("id"),
        "thread_id": data.get("threadId"),
        "subject": _extract_header(headers, "Subject"),
        "from": _extract_header(headers, "From"),
        "to": _extract_header(headers, "To"),
        "date": _extract_header(headers, "Date"),
        "snippet": data.get("snippet"),
        "label_ids": data.get("labelIds", []),
    }


def register_gmail_tools(mcp: FastMCP) -> None:
    """Register Gmail tools with the MCP server."""

    @mcp.tool(
        name="search_emails",
        description="Search Gmail messages using Gmail search query syntax (e.g., 'from:user@example.com', 'subject:report', 'is:unread', 'after:2025/01/01'). Returns message metadata for each result.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def search_emails(
        ctx: Context,
        query: str = "",
        max_results: int = 10,
        page_token: str | None = None,
    ) -> dict:
        """Search for Gmail messages.

        Args:
            query: Gmail search query (e.g., 'from:user@example.com is:unread').
            max_results: Maximum number of messages to return (default: 10).
            page_token: Token for fetching the next page of results.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                "/gmail/v1/users/me/messages",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                params={
                    "q": query or None,
                    "maxResults": max_results,
                    "pageToken": page_token,
                },
            )

            message_stubs = data.get("messages", [])
            if not message_stubs:
                return {
                    "success": True,
                    "messages": [],
                    "count": 0,
                    "next_page_token": data.get("nextPageToken"),
                }

            # Fetch metadata for each message in parallel
            tasks = [
                request(
                    "GET",
                    f"/gmail/v1/users/me/messages/{msg['id']}",
                    token=token,
                    base_url=GOOGLE_GMAIL_API_URL,
                    params={
                        "format": "metadata",
                        "metadataHeaders": "Subject,From,To,Date",
                    },
                )
                for msg in message_stubs
            ]
            details = await asyncio.gather(*tasks)

            messages = [_parse_message_metadata(d) for d in details]

            return {
                "success": True,
                "messages": messages,
                "count": len(messages),
                "next_page_token": data.get("nextPageToken"),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="read_email",
        description="Read the full content of a Gmail message by its ID. Returns headers, body text, and attachment metadata.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def read_email(
        ctx: Context,
        message_id: str,
    ) -> dict:
        """Read a full email message.

        Args:
            message_id: The Gmail message ID.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/gmail/v1/users/me/messages/{message_id}",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                params={"format": "full"},
            )

            payload = data.get("payload", {})
            headers = payload.get("headers", [])
            body = _extract_email_body(payload)

            # Extract attachment info
            attachments = []
            for part in payload.get("parts", []):
                filename = part.get("filename")
                if filename and part.get("body", {}).get("attachmentId"):
                    attachments.append(
                        {
                            "filename": filename,
                            "mime_type": part.get("mimeType"),
                            "size": part.get("body", {}).get("size"),
                        }
                    )

            return {
                "success": True,
                "message": {
                    "id": data.get("id"),
                    "thread_id": data.get("threadId"),
                    "subject": _extract_header(headers, "Subject"),
                    "from": _extract_header(headers, "From"),
                    "to": _extract_header(headers, "To"),
                    "cc": _extract_header(headers, "Cc"),
                    "date": _extract_header(headers, "Date"),
                    "body": body,
                    "label_ids": data.get("labelIds", []),
                    "attachments": attachments if attachments else None,
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="send_email",
        description="Send an email via Gmail.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def send_email(
        ctx: Context,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict:
        """Send an email.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body text (plain text).
            cc: CC recipient email address.
            bcc: BCC recipient email address.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            raw = _build_raw_message(to, subject, body, cc=cc, bcc=bcc)

            data = await request(
                "POST",
                "/gmail/v1/users/me/messages/send",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                json={"raw": raw},
            )

            return {
                "success": True,
                "message": {
                    "id": data.get("id"),
                    "thread_id": data.get("threadId"),
                    "label_ids": data.get("labelIds", []),
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="create_draft",
        description="Create a draft email in Gmail without sending it.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def create_draft(
        ctx: Context,
        to: str,
        subject: str,
        body: str,
        cc: str | None = None,
        bcc: str | None = None,
    ) -> dict:
        """Create an email draft.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Email body text (plain text).
            cc: CC recipient email address.
            bcc: BCC recipient email address.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            raw = _build_raw_message(to, subject, body, cc=cc, bcc=bcc)

            data = await request(
                "POST",
                "/gmail/v1/users/me/drafts",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                json={"message": {"raw": raw}},
            )

            message = data.get("message", {})
            return {
                "success": True,
                "draft": {
                    "id": data.get("id"),
                    "message_id": message.get("id"),
                    "thread_id": message.get("threadId"),
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_thread",
        description="Get all messages in a Gmail thread by thread ID. Returns the full conversation.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_thread(
        ctx: Context,
        thread_id: str,
    ) -> dict:
        """Get all messages in a thread.

        Args:
            thread_id: The Gmail thread ID.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/gmail/v1/users/me/threads/{thread_id}",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                params={"format": "full"},
            )

            messages = []
            for msg in data.get("messages", []):
                payload = msg.get("payload", {})
                headers = payload.get("headers", [])
                messages.append(
                    {
                        "id": msg.get("id"),
                        "subject": _extract_header(headers, "Subject"),
                        "from": _extract_header(headers, "From"),
                        "to": _extract_header(headers, "To"),
                        "date": _extract_header(headers, "Date"),
                        "snippet": msg.get("snippet"),
                        "body": _extract_email_body(payload),
                    }
                )

            return {
                "success": True,
                "thread_id": data.get("id"),
                "messages": messages,
                "count": len(messages),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="list_labels",
        description="List all Gmail labels (inbox, sent, custom labels, etc.).",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def list_labels(
        ctx: Context,
    ) -> dict:
        """List all labels in the user's Gmail account."""
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                "/gmail/v1/users/me/labels",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
            )

            labels = [
                {
                    "id": label.get("id"),
                    "name": label.get("name"),
                    "type": label.get("type"),
                }
                for label in data.get("labels", [])
            ]

            return {
                "success": True,
                "labels": labels,
                "count": len(labels),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="modify_message",
        description="Modify the labels on a Gmail message. Use to mark as read (remove 'UNREAD'), archive (remove 'INBOX'), star (add 'STARRED'), etc.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def modify_message(
        ctx: Context,
        message_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        """Modify labels on a message.

        Args:
            message_id: The Gmail message ID.
            add_label_ids: Label IDs to add (e.g., ['STARRED', 'IMPORTANT']).
            remove_label_ids: Label IDs to remove (e.g., ['UNREAD', 'INBOX']).
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/gmail/v1/users/me/messages/{message_id}/modify",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
                json={
                    "addLabelIds": add_label_ids or [],
                    "removeLabelIds": remove_label_ids or [],
                },
            )

            return {
                "success": True,
                "message_id": data.get("id"),
                "label_ids": data.get("labelIds", []),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="trash_message",
        description="Move a Gmail message to the trash.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def trash_message(
        ctx: Context,
        message_id: str,
    ) -> dict:
        """Trash a message.

        Args:
            message_id: The Gmail message ID.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/gmail/v1/users/me/messages/{message_id}/trash",
                token=token,
                base_url=GOOGLE_GMAIL_API_URL,
            )

            return {
                "success": True,
                "message_id": data.get("id"),
                "trashed": True,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}
