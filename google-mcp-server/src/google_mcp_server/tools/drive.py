"""Drive Tools.

Tools for Google Drive: list_files, get_file, get_file_content, delete_file.
"""

from fastmcp import FastMCP, Context

from ..auth import auth_provider, get_google_token, GOOGLE_API_URL
from ..client import GoogleClientError, request


# Google Workspace MIME type prefix — these files need /export instead of ?alt=media
GOOGLE_WORKSPACE_PREFIX = "application/vnd.google-apps."

# Default export MIME types for Google Workspace document types
WORKSPACE_EXPORT_DEFAULTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}


def register_drive_tools(mcp: FastMCP) -> None:
    """Register drive tools with the MCP server."""

    @mcp.tool(
        name="list_files",
        description="List or search files in Google Drive. Supports Drive search query syntax (e.g., \"name contains 'report'\", \"mimeType='application/pdf'\", \"'folderId' in parents\").",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def list_files(
        ctx: Context,
        q: str | None = None,
        order_by: str | None = None,
        page_size: int = 20,
        page_token: str | None = None,
    ) -> dict:
        """List or search files in Drive.

        Args:
            q: Drive search query (e.g., "name contains 'report'", "mimeType='application/pdf'").
            order_by: Sort order (e.g., "modifiedTime desc", "name").
            page_size: Maximum number of files to return.
            page_token: Token for fetching the next page.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                "/drive/v3/files",
                token=token,
                params={
                    "q": q,
                    "orderBy": order_by,
                    "pageSize": page_size,
                    "pageToken": page_token,
                    "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,parents),nextPageToken",
                },
            )

            files = [
                {
                    "id": f["id"],
                    "name": f.get("name"),
                    "mimeType": f.get("mimeType"),
                    "size": f.get("size"),
                    "modifiedTime": f.get("modifiedTime"),
                    "webViewLink": f.get("webViewLink"),
                    "parents": f.get("parents"),
                }
                for f in data.get("files", [])
            ]

            return {
                "success": True,
                "files": files,
                "count": len(files),
                "next_page_token": data.get("nextPageToken"),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_file",
        description="Get metadata of a Google Drive file (name, type, size, links, etc.).",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_file(
        ctx: Context,
        file_id: str,
    ) -> dict:
        """Get file metadata.

        Args:
            file_id: The Drive file ID.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/drive/v3/files/{file_id}",
                token=token,
                params={
                    "fields": "id,name,mimeType,size,modifiedTime,createdTime,webViewLink,parents,description",
                },
            )

            file_info = {
                "id": data["id"],
                "name": data.get("name"),
                "mimeType": data.get("mimeType"),
                "size": data.get("size"),
                "modifiedTime": data.get("modifiedTime"),
                "createdTime": data.get("createdTime"),
                "webViewLink": data.get("webViewLink"),
                "parents": data.get("parents"),
                "description": data.get("description"),
            }
            return {"success": True, "file": file_info}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_file_content",
        description="Download the content of a Google Drive file. For Google Workspace documents (Docs, Sheets, Slides), exports to text/plain or text/csv by default. For regular files, downloads the raw content. Override the export format with export_mime_type.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_file_content(
        ctx: Context,
        file_id: str,
        export_mime_type: str | None = None,
    ) -> dict:
        """Download or export file content.

        Args:
            file_id: The Drive file ID.
            export_mime_type: MIME type to export Google Workspace docs as
                (e.g., "text/plain", "text/csv", "application/pdf").
                Auto-detected if not specified.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            # Step 1: Get file metadata to determine type
            metadata = await request(
                "GET",
                f"/drive/v3/files/{file_id}",
                token=token,
                params={"fields": "mimeType,name"},
            )

            mime_type = metadata.get("mimeType", "")
            name = metadata.get("name", "")

            # Step 2: Download or export based on type
            if mime_type.startswith(GOOGLE_WORKSPACE_PREFIX):
                # Google Workspace doc — use export endpoint
                target_mime = export_mime_type or WORKSPACE_EXPORT_DEFAULTS.get(
                    mime_type, "text/plain"
                )
                content = await request(
                    "GET",
                    f"/drive/v3/files/{file_id}/export",
                    token=token,
                    params={"mimeType": target_mime},
                    raw_response=True,
                )
            else:
                # Regular file — download with alt=media
                content = await request(
                    "GET",
                    f"/drive/v3/files/{file_id}",
                    token=token,
                    params={"alt": "media"},
                    raw_response=True,
                )

            return {
                "success": True,
                "name": name,
                "mime_type": mime_type,
                "content": content,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="delete_file",
        description="Delete a file from Google Drive.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def delete_file(
        ctx: Context,
        file_id: str,
    ) -> dict:
        """Delete a file from Drive.

        Args:
            file_id: The Drive file ID to delete.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            await request(
                "DELETE",
                f"/drive/v3/files/{file_id}",
                token=token,
            )

            return {"success": True, "deleted": True}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}
