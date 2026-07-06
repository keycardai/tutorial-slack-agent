"""Sheets Tools.

Tools for Google Sheets: create_spreadsheet, get_spreadsheet, get_values,
update_values, append_values, clear_values, add_sheet, batch_get_values.
"""

from urllib.parse import quote

from fastmcp import FastMCP, Context

from ..auth import auth_provider, get_google_token, GOOGLE_API_URL
from ..client import GoogleClientError, request, GOOGLE_SHEETS_API_URL


def _spreadsheet_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def register_sheets_tools(mcp: FastMCP) -> None:
    """Register Google Sheets tools with the MCP server."""

    @mcp.tool(
        name="create_spreadsheet",
        description="Create a new Google Spreadsheet with a title. Returns the spreadsheet ID and URL.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def create_spreadsheet(
        ctx: Context,
        title: str,
    ) -> dict:
        """Create a new Google Spreadsheet.

        Args:
            title: Title for the new spreadsheet.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                "/v4/spreadsheets",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                json={"properties": {"title": title}},
            )

            spreadsheet_id = data["spreadsheetId"]
            return {
                "success": True,
                "spreadsheet": {
                    "spreadsheet_id": spreadsheet_id,
                    "title": data.get("properties", {}).get("title"),
                    "spreadsheet_url": _spreadsheet_url(spreadsheet_id),
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_spreadsheet",
        description="Get spreadsheet metadata including title and the list of sheet tabs (without grid data).",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_spreadsheet(
        ctx: Context,
        spreadsheet_id: str,
    ) -> dict:
        """Get spreadsheet metadata.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/v4/spreadsheets/{spreadsheet_id}",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                params={
                    "fields": "spreadsheetId,properties.title,sheets.properties",
                },
            )

            sheets = [
                {
                    "sheet_id": s.get("properties", {}).get("sheetId"),
                    "title": s.get("properties", {}).get("title"),
                    "index": s.get("properties", {}).get("index"),
                }
                for s in data.get("sheets", [])
            ]

            return {
                "success": True,
                "spreadsheet_id": data.get("spreadsheetId"),
                "title": data.get("properties", {}).get("title"),
                "sheets": sheets,
                "spreadsheet_url": _spreadsheet_url(spreadsheet_id),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_values",
        description="Read cell values from a range in a spreadsheet. Range uses A1 notation (e.g., 'Sheet1!A1:D10').",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_values(
        ctx: Context,
        spreadsheet_id: str,
        range: str,
    ) -> dict:
        """Read values from a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range: A1 notation range (e.g., 'Sheet1!A1:D10').
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/v4/spreadsheets/{spreadsheet_id}/values/{quote(range, safe='')}",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
            )

            return {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "range": data.get("range"),
                "values": data.get("values", []),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="update_values",
        description="Write values to a range in a spreadsheet. Overwrites existing cells. Uses A1 notation for the range.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def update_values(
        ctx: Context,
        spreadsheet_id: str,
        range: str,
        values: list[list],
        value_input_option: str = "USER_ENTERED",
    ) -> dict:
        """Write values to a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range: A1 notation range (e.g., 'Sheet1!A1:B2').
            values: 2D array of cell values (list of rows).
            value_input_option: 'USER_ENTERED' (parses formulas/dates, default)
                or 'RAW' (stores input literally).
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "PUT",
                f"/v4/spreadsheets/{spreadsheet_id}/values/{quote(range, safe='')}",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                params={"valueInputOption": value_input_option},
                json={"values": values},
            )

            return {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "updated_range": data.get("updatedRange"),
                "updated_rows": data.get("updatedRows", 0),
                "updated_columns": data.get("updatedColumns", 0),
                "updated_cells": data.get("updatedCells", 0),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="append_values",
        description="Append rows to a range/table in a spreadsheet. Finds the next empty row after the given range and inserts there.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def append_values(
        ctx: Context,
        spreadsheet_id: str,
        range: str,
        values: list[list],
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict:
        """Append rows to a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range: A1 notation range to search for the table (e.g., 'Sheet1!A:B').
            values: 2D array of rows to append.
            value_input_option: 'USER_ENTERED' (default) or 'RAW'.
            insert_data_option: 'INSERT_ROWS' (default) shifts existing data
                down, or 'OVERWRITE' writes over any existing data.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/v4/spreadsheets/{spreadsheet_id}/values/{quote(range, safe='')}:append",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                params={
                    "valueInputOption": value_input_option,
                    "insertDataOption": insert_data_option,
                },
                json={"values": values},
            )

            updates = data.get("updates", {})
            return {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "table_range": data.get("tableRange"),
                "updated_range": updates.get("updatedRange"),
                "updated_rows": updates.get("updatedRows", 0),
                "updated_cells": updates.get("updatedCells", 0),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="clear_values",
        description="Clear cell values in a range. Removes content but leaves formatting.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def clear_values(
        ctx: Context,
        spreadsheet_id: str,
        range: str,
    ) -> dict:
        """Clear values from a range.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            range: A1 notation range (e.g., 'Sheet1!A1:B10').
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/v4/spreadsheets/{spreadsheet_id}/values/{quote(range, safe='')}:clear",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                json={},
            )

            return {
                "success": True,
                "spreadsheet_id": data.get("spreadsheetId", spreadsheet_id),
                "cleared_range": data.get("clearedRange"),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="add_sheet",
        description="Add a new sheet (tab) to an existing spreadsheet. Returns the new sheet's ID and title.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def add_sheet(
        ctx: Context,
        spreadsheet_id: str,
        sheet_title: str,
    ) -> dict:
        """Add a new sheet tab.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            sheet_title: Title for the new sheet.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "POST",
                f"/v4/spreadsheets/{spreadsheet_id}:batchUpdate",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                json={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {"title": sheet_title}
                            }
                        }
                    ]
                },
            )

            replies = data.get("replies", [])
            added = (
                replies[0].get("addSheet", {}).get("properties", {})
                if replies
                else {}
            )

            return {
                "success": True,
                "spreadsheet_id": spreadsheet_id,
                "sheet": {
                    "sheet_id": added.get("sheetId"),
                    "title": added.get("title"),
                    "index": added.get("index"),
                },
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="batch_get_values",
        description="Read cell values from multiple ranges in a single call. Each range uses A1 notation.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def batch_get_values(
        ctx: Context,
        spreadsheet_id: str,
        ranges: list[str],
    ) -> dict:
        """Read values from multiple ranges.

        Args:
            spreadsheet_id: The ID of the spreadsheet.
            ranges: List of A1 notation ranges (e.g., ['Sheet1!A1:B2', 'Sheet2!C:C']).
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            # httpx serializes list values as repeated query params (ranges=...&ranges=...)
            data = await request(
                "GET",
                f"/v4/spreadsheets/{spreadsheet_id}/values:batchGet",
                token=token,
                base_url=GOOGLE_SHEETS_API_URL,
                params={"ranges": ranges},
            )

            value_ranges = [
                {
                    "range": vr.get("range"),
                    "values": vr.get("values", []),
                }
                for vr in data.get("valueRanges", [])
            ]

            return {
                "success": True,
                "spreadsheet_id": data.get("spreadsheetId", spreadsheet_id),
                "value_ranges": value_ranges,
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}
