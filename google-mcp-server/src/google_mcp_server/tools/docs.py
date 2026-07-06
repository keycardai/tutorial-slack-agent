"""Docs Tools.

Tools for Google Docs: create_document, read_document, append_text, replace_text.
"""

from typing import Any

from fastmcp import FastMCP, Context

from ..auth import auth_provider, get_google_token, GOOGLE_API_URL
from ..client import GoogleClientError, request, GOOGLE_DOCS_API_URL


def _extract_document_text(body_content: list[dict[str, Any]]) -> str:
    """Recursively extract text from Google Docs body content.

    Handles paragraphs (paragraph -> elements -> textRun -> content)
    and tables (table -> tableRows -> tableCells -> content -> recurse).
    """
    text_parts: list[str] = []
    for element in body_content:
        if "paragraph" in element:
            for elem in element["paragraph"].get("elements", []):
                text_run = elem.get("textRun")
                if text_run:
                    text_parts.append(text_run.get("content", ""))
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                for cell in row.get("tableCells", []):
                    cell_text = _extract_document_text(cell.get("content", []))
                    if cell_text.strip():
                        text_parts.append(cell_text)
    return "".join(text_parts)


def register_docs_tools(mcp: FastMCP) -> None:
    """Register Google Docs tools with the MCP server."""

    @mcp.tool(
        name="create_document",
        description="Create a new blank Google Doc with a title. Returns the document ID and URL.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def create_document(
        ctx: Context,
        title: str,
    ) -> dict:
        """Create a new Google Doc.

        Args:
            title: Title for the new document.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                "/v1/documents",
                token=token,
                base_url=GOOGLE_DOCS_API_URL,
                json={"title": title},
            )

            document_id = data["documentId"]
            return {
                "success": True,
                "document": {
                    "document_id": document_id,
                    "title": data.get("title"),
                    "document_url": f"https://docs.google.com/document/d/{document_id}/edit",
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="read_document",
        description="Read the text content of a Google Doc. Returns the full document text extracted from all paragraphs and tables.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def read_document(
        ctx: Context,
        document_id: str,
    ) -> dict:
        """Read the content of a Google Doc.

        Args:
            document_id: The ID of the Google Doc to read.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/v1/documents/{document_id}",
                token=token,
                base_url=GOOGLE_DOCS_API_URL,
            )

            body_content = data.get("body", {}).get("content", [])
            text = _extract_document_text(body_content)

            return {
                "success": True,
                "document_id": data.get("documentId"),
                "title": data.get("title"),
                "text": text,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="append_text",
        description="Append text to the end of a Google Doc.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def append_text(
        ctx: Context,
        document_id: str,
        text: str,
    ) -> dict:
        """Append text to the end of a document.

        Args:
            document_id: The ID of the Google Doc.
            text: The text to append.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            await request(
                "POST",
                f"/v1/documents/{document_id}:batchUpdate",
                token=token,
                base_url=GOOGLE_DOCS_API_URL,
                json={
                    "requests": [
                        {
                            "insertText": {
                                "endOfSegmentLocation": {"segmentId": ""},
                                "text": text,
                            }
                        }
                    ]
                },
            )

            return {
                "success": True,
                "document_id": document_id,
                "appended": True,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="replace_text",
        description="Find and replace all occurrences of a text string in a Google Doc.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def replace_text(
        ctx: Context,
        document_id: str,
        find_text: str,
        replace_with: str,
        match_case: bool = True,
    ) -> dict:
        """Find and replace text in a document.

        Args:
            document_id: The ID of the Google Doc.
            find_text: The text to search for.
            replace_with: The replacement text.
            match_case: Whether the search is case-sensitive (default: True).
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/v1/documents/{document_id}:batchUpdate",
                token=token,
                base_url=GOOGLE_DOCS_API_URL,
                json={
                    "requests": [
                        {
                            "replaceAllText": {
                                "containsText": {
                                    "text": find_text,
                                    "matchCase": match_case,
                                },
                                "replaceText": replace_with,
                            }
                        }
                    ]
                },
            )

            replies = data.get("replies", [])
            occurrences = 0
            if replies:
                occurrences = (
                    replies[0]
                    .get("replaceAllText", {})
                    .get("occurrencesChanged", 0)
                )

            return {
                "success": True,
                "document_id": document_id,
                "occurrences_changed": occurrences,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}
