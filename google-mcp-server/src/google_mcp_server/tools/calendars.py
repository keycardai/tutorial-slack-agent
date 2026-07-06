"""Calendar Tools.

Tools for Google Calendar: list_calendars, list_events, get_event,
create_event, update_event, delete_event.
"""

from fastmcp import FastMCP, Context

from ..auth import auth_provider, get_google_token, GOOGLE_API_URL
from ..client import GoogleClientError, request


def register_calendar_tools(mcp: FastMCP) -> None:
    """Register calendar tools with the MCP server."""

    @mcp.tool(
        name="list_calendars",
        description="List the user's Google calendars. Returns calendar id, name, time zone, and access role.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def list_calendars(
        ctx: Context,
        max_results: int = 100,
        page_token: str | None = None,
    ) -> dict:
        """List calendars the user has access to.

        Args:
            max_results: Maximum number of calendars to return.
            page_token: Token for fetching the next page of results.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                "/calendar/v3/users/me/calendarList",
                token=token,
                params={
                    "maxResults": max_results,
                    "pageToken": page_token,
                },
            )

            calendars = [
                {
                    "id": cal["id"],
                    "summary": cal.get("summary"),
                    "description": cal.get("description"),
                    "primary": cal.get("primary", False),
                    "timeZone": cal.get("timeZone"),
                    "accessRole": cal.get("accessRole"),
                }
                for cal in data.get("items", [])
            ]

            return {
                "success": True,
                "calendars": calendars,
                "count": len(calendars),
                "next_page_token": data.get("nextPageToken"),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="list_events",
        description="List events from a Google Calendar. Supports time range filtering, text search, and pagination. Times use RFC 3339 format (e.g., '2025-01-15T09:00:00-07:00').",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def list_events(
        ctx: Context,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        q: str | None = None,
        max_results: int = 50,
        page_token: str | None = None,
        single_events: bool = True,
        order_by: str | None = "startTime",
    ) -> dict:
        """List events from a calendar.

        Args:
            calendar_id: Calendar ID (default: "primary" for the user's main calendar).
            time_min: Lower bound for event start time (RFC 3339, e.g., '2025-01-15T00:00:00Z').
            time_max: Upper bound for event start time (RFC 3339).
            q: Free text search terms to find events.
            max_results: Maximum number of events to return.
            page_token: Token for fetching the next page.
            single_events: Whether to expand recurring events into individual instances.
            order_by: Sort order - "startTime" (requires single_events=True) or "updated".
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/calendar/v3/calendars/{calendar_id}/events",
                token=token,
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "q": q,
                    "maxResults": max_results,
                    "pageToken": page_token,
                    "singleEvents": str(single_events).lower(),
                    "orderBy": order_by,
                },
            )

            events = [
                {
                    "id": event["id"],
                    "summary": event.get("summary"),
                    "description": event.get("description"),
                    "start": event.get("start"),
                    "end": event.get("end"),
                    "location": event.get("location"),
                    "status": event.get("status"),
                    "htmlLink": event.get("htmlLink"),
                    "creator": event.get("creator"),
                    "organizer": event.get("organizer"),
                    "attendees": event.get("attendees"),
                }
                for event in data.get("items", [])
            ]

            return {
                "success": True,
                "events": events,
                "count": len(events),
                "next_page_token": data.get("nextPageToken"),
            }
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="get_event",
        description="Get details of a specific calendar event by its ID.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def get_event(
        ctx: Context,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict:
        """Get a single event's details.

        Args:
            event_id: The event ID.
            calendar_id: Calendar ID (default: "primary").
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            data = await request(
                "GET",
                f"/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                token=token,
            )

            event = {
                "id": data["id"],
                "summary": data.get("summary"),
                "description": data.get("description"),
                "start": data.get("start"),
                "end": data.get("end"),
                "location": data.get("location"),
                "status": data.get("status"),
                "htmlLink": data.get("htmlLink"),
                "creator": data.get("creator"),
                "organizer": data.get("organizer"),
                "attendees": data.get("attendees"),
                "recurrence": data.get("recurrence"),
                "created": data.get("created"),
                "updated": data.get("updated"),
            }
            return {"success": True, "event": event}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="create_event",
        description="Create a new calendar event. Times use RFC 3339 format (e.g., '2025-01-15T09:00:00-07:00'). Attendees are specified as a list of email addresses.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def create_event(
        ctx: Context,
        summary: str,
        start_time: str,
        end_time: str,
        calendar_id: str = "primary",
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        time_zone: str | None = None,
    ) -> dict:
        """Create a new event on a calendar.

        Args:
            summary: Event title.
            start_time: Start time in RFC 3339 format.
            end_time: End time in RFC 3339 format.
            calendar_id: Calendar ID (default: "primary").
            description: Event description.
            location: Event location.
            attendees: List of attendee email addresses.
            time_zone: Time zone (e.g., "America/Los_Angeles"). Applied to start/end times.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            body = {
                "summary": summary,
                "start": {"dateTime": start_time},
                "end": {"dateTime": end_time},
            }

            if time_zone:
                body["start"]["timeZone"] = time_zone
                body["end"]["timeZone"] = time_zone

            if description is not None:
                body["description"] = description
            if location is not None:
                body["location"] = location
            if attendees is not None:
                body["attendees"] = [{"email": email} for email in attendees]

            data = await request(
                "POST",
                f"/calendar/v3/calendars/{calendar_id}/events",
                token=token,
                json=body,
            )

            event = {
                "id": data["id"],
                "summary": data.get("summary"),
                "htmlLink": data.get("htmlLink"),
                "start": data.get("start"),
                "end": data.get("end"),
                "status": data.get("status"),
            }
            return {"success": True, "event": event}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="update_event",
        description="Update an existing calendar event. Only provide fields you want to change. Times use RFC 3339 format.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def update_event(
        ctx: Context,
        event_id: str,
        calendar_id: str = "primary",
        summary: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        description: str | None = None,
        location: str | None = None,
        attendees: list[str] | None = None,
        time_zone: str | None = None,
    ) -> dict:
        """Update fields on an existing event.

        Args:
            event_id: The event ID to update.
            calendar_id: Calendar ID (default: "primary").
            summary: New event title.
            start_time: New start time in RFC 3339 format.
            end_time: New end time in RFC 3339 format.
            description: New event description.
            location: New event location.
            attendees: New list of attendee email addresses (replaces existing).
            time_zone: Time zone for start/end times.
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            body = {}
            if summary is not None:
                body["summary"] = summary
            if description is not None:
                body["description"] = description
            if location is not None:
                body["location"] = location
            if start_time is not None:
                body["start"] = {"dateTime": start_time}
                if time_zone:
                    body["start"]["timeZone"] = time_zone
            if end_time is not None:
                body["end"] = {"dateTime": end_time}
                if time_zone:
                    body["end"]["timeZone"] = time_zone
            if attendees is not None:
                body["attendees"] = [{"email": email} for email in attendees]

            data = await request(
                "PATCH",
                f"/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                token=token,
                json=body,
            )

            event = {
                "id": data["id"],
                "summary": data.get("summary"),
                "htmlLink": data.get("htmlLink"),
                "start": data.get("start"),
                "end": data.get("end"),
                "status": data.get("status"),
            }
            return {"success": True, "event": event}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}

    @mcp.tool(
        name="delete_event",
        description="Delete a calendar event by its ID.",
    )
    @auth_provider.grant(GOOGLE_API_URL)
    async def delete_event(
        ctx: Context,
        event_id: str,
        calendar_id: str = "primary",
    ) -> dict:
        """Delete an event from a calendar.

        Args:
            event_id: The event ID to delete.
            calendar_id: Calendar ID (default: "primary").
        """
        try:
            access_ctx = await ctx.get_state("keycardai")
            token = get_google_token(access_ctx)

            await request(
                "DELETE",
                f"/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                token=token,
            )

            return {"success": True, "deleted": True}
        except GoogleClientError as e:
            return {"success": False, "error": e.message, "isError": True}
        except ValueError as e:
            return {"success": False, "error": str(e), "isError": True}
