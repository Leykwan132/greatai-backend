from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import requests
import base64
import datetime
import logging
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.message import EmailMessage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Google Services API", version="1.0.0")

SCOPES = ["https://www.googleapis.com/auth/calendar", "https://mail.google.com/"]


# Pydantic models for request/response
class EmailRequest(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email content")


class ReplyRequest(BaseModel):
    message_id: str = Field(..., description="ID of email to reply to")
    to: str = Field(..., description="Recipient email address")
    body: str = Field(..., description="Reply content")
    reply_all: bool = Field(False, description="Reply to all recipients")


class EditEventRequest(BaseModel):
    event_id: str = Field(..., description="Event ID to edit")
    title: Optional[str] = Field(None, description="New event title")
    start_time: Optional[str] = Field(None, description="New start time (ISO format)")
    end_time: Optional[str] = Field(None, description="New end time (ISO format)")
    location: Optional[str] = Field(None, description="New location")
    description: Optional[str] = Field(None, description="New description")


class EmailFilters(BaseModel):
    label: Optional[str] = Field(None, description="Filter by label")


# Token management
def get_access_token():
    """Load access token from token.json file"""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    return creds


# Gmail endpoints
def get_message_data(message):
    """Extract snippet, subject, and from fields from a Gmail message"""
    subject = ""
    from_email = ""

    # Extract subject and from email from headers
    for header in message.get("payload", {}).get("headers", []):
        name = header.get("name", "").lower()
        value = header.get("value", "")

        if name == "subject":
            subject = value
        elif name == "from":
            from_email = value
            # No need to continue once we have both fields
            if subject and from_email:
                break

    return {
        "email_id": message["id"],
        "snippet": message.get("snippet", ""),
        "subject": subject,
        "from": from_email,
    }


@app.get("/emails", response_model=Dict[str, Any])
async def get_emails(
    label: Optional[str] = None,
    access_token: str = Depends(get_access_token),
):
    """Get emails filtered by label with detailed information"""
    try:
        service = build("gmail", "v1", credentials=access_token)
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                q=f"label:{label}" if label else "",
                maxResults=10,  # Limit to 10 most recent emails by default
            )
            .execute()
        )

        messages = results.get("messages", [])

        if not messages:
            return {"emails": [], "count": 0}

        # Get full message details for each email
        detailed_messages = []
        for message in messages:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message["id"],
                    format="full",  # Get full message with payload
                )
                .execute()
            )
            detailed_messages.append(get_message_data(msg))

        return {"emails": detailed_messages, "count": len(detailed_messages)}

    except requests.exceptions.RequestException as e:
        logger.error(f"Gmail API error: {e}")
        raise HTTPException(status_code=500, detail=f"Gmail API error: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@app.post("/emails/reply")
async def reply_to_email(
    reply_request: ReplyRequest, access_token: str = Depends(get_access_token)
):
    """Reply to an email"""
    print("reply_request", reply_request)
    try:
        service = build("gmail", "v1", credentials=access_token)
        message = EmailMessage()

        message.set_content(reply_request.body)

        # Headers must match
        message["To"] = reply_request.to
        message["From"] = "me"
        # Add 'Re: ' prefix if not already present

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=reply_request.message_id)
            .execute()
        )

        subject = msg["snippet"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message["Subject"] = subject

        # Threading headers
        message["In-Reply-To"] = (
            reply_request.message_id
        )  # The Message-ID of the email you’re replying to
        message["References"] = (
            reply_request.message_id
        )  # Can be a chain of IDs if long thread

        # Encode message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        create_message = {"raw": encoded_message, "threadId": reply_request.message_id}

        send_message = (
            service.users().messages().send(userId="me", body=create_message).execute()
        )

        print(f'Reply sent. Message Id: {send_message["id"]}')
        return send_message

    except HttpError as error:
        print(f"An error occurred: {error}")
        return None


# Calendar endpoints
@app.get("/calendar/events")
async def get_calendar_events(
    access_token: str = Depends(get_access_token),
) -> Dict[str, Any]:
    """Get calendar events for today

    Returns:
        Dict[str, Any]: List of events with id, summary, start, and end times
    """
    try:
        service = build("calendar", "v3", credentials=access_token)

        # Get today's date at 00:00:00 and 23:59:59.999999
        today = datetime.datetime.now(tz=datetime.timezone.utc)
        start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

        # Call the Calendar API
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        if not events:
            return {"events": []}

        # Extract only the required fields
        simplified_events = []
        for event in events:
            # Get the start time of the event
            start = event["start"].get("dateTime") or event["start"].get("date")
            event_date = datetime.datetime.fromisoformat(
                start.replace("Z", "+00:00")
            ).date()

            # Only include events for today
            if event_date == today.date():
                simplified_events.append(
                    {
                        "eventId": event.get("id"),
                        "summary": event.get("summary", "No Title"),
                        "start": start,
                        "end": event["end"].get("dateTime") or event["end"].get("date"),
                    }
                )

        return {"events": simplified_events}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class EventDateTime(BaseModel):
    """Model for event date/time fields"""

    date: Optional[str] = Field(
        None,
        description='The date, in the format "yyyy-mm-dd", if this is an all-day event.',
    )
    dateTime: Optional[str] = Field(
        None,
        description="The time, as a combined date-time value (formatted according to RFC3339).",
    )
    timeZone: Optional[str] = Field(
        None, description="The time zone in which the time is specified."
    )


class CalendarEventCreate(BaseModel):
    """Request model for creating calendar events"""

    summary: str = Field(..., description="The event's title")
    location: Optional[str] = Field(None, description="The event's location")
    description: Optional[str] = Field(None, description="The event's description")
    start: EventDateTime = Field(
        ..., description="The (inclusive) start time of the event"
    )
    end: EventDateTime = Field(..., description="The (exclusive) end time of the event")
    attendees: Optional[List[Dict[str, str]]] = Field(
        None, description="List of attendees' email addresses"
    )
    reminders: Optional[Dict[str, Any]] = Field(
        None, description="Reminder settings for the event"
    )
    recurrence: Optional[List[str]] = Field(
        None,
        description="List of RRULE, EXRULE, RDATE and EXDATE lines for a recurring event",
    )


class CalendarEventUpdate(BaseModel):
    """Request model for updating calendar events"""

    start: Optional[EventDateTime] = Field(
        None, description="The (inclusive) start time of the event"
    )
    end: Optional[EventDateTime] = Field(
        None, description="The (exclusive) end time of the event"
    )
    summary: Optional[str] = Field(None, description="The event's title")
    description: Optional[str] = Field(None, description="The event's description")
    location: Optional[str] = Field(None, description="The event's location")


@app.post("/calendar/events")
async def create_calendar_event(
    event_data: CalendarEventCreate,
    access_token: str = Depends(get_access_token),
):
    """
    Create a new calendar event. The date will always be set to today while preserving the input time.

    Example request body:
    ```json
    {
        "summary": "Test Event",
        "start": {
            "dateTime": "2025-09-22T09:00:00+08:00",
            "timeZone": "Asia/Kuala_Lumpur"
        },
        "end": {
            "dateTime": "2025-09-22T10:00:00+08:00",
            "timeZone": "Asia/Kuala_Lumpur"
        },
        "location": "Meeting Room 1",
        "description": "Test meeting description",
        "attendees": [
            {"email": "attendee@example.com"}
        ],
    }
    ```

    Returns:
        dict: Created event details including eventId, htmlLink, and other metadata
    """
    try:
        service = build("calendar", "v3", credentials=access_token)
        today = datetime.datetime.now(tz=datetime.timezone.utc).date()

        # Convert Pydantic model to dictionary
        event_dict = event_data.dict(exclude_unset=True)

        def adjust_datetime(dt_str: str, timezone_str: str) -> str:
            # Parse the input datetime
            dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            # Get the timezone object
            tz = datetime.timezone(
                datetime.timedelta(hours=int(timezone_str.split(":")[0]))
            )
            # Set the date to today while preserving the time
            adjusted_dt = datetime.datetime.combine(today, dt.time()).replace(tzinfo=tz)
            # Format back to ISO format
            return adjusted_dt.isoformat()

        # Adjust start and end times to today's date
        if "start" in event_dict and "dateTime" in event_dict["start"]:
            timezone = event_dict["start"].get("timeZone", "Asia/Kuala_Lumpur")
            event_dict["start"]["dateTime"] = adjust_datetime(
                event_dict["start"]["dateTime"], timezone
            )

        if "end" in event_dict and "dateTime" in event_dict["end"]:
            # Use start's timezone if end timezone is not specified
            timezone = event_dict["end"].get(
                "timeZone",
                event_dict.get("start", {}).get("timeZone", "Asia/Kuala_Lumpur"),
            )
            event_dict["end"]["dateTime"] = adjust_datetime(
                event_dict["end"]["dateTime"], timezone
            )

        # Create the event
        event = (
            service.events()
            .insert(
                calendarId="primary",
                body=event_dict,
                sendUpdates="all",  # Send notifications to attendees
            )
            .execute()
        )

        # Return the created event with a simplified response
        return {
            "eventId": event.get("id"),
            "htmlLink": event.get("htmlLink"),
            "summary": event.get("summary"),
            "status": event.get("status"),
            "created": event.get("created"),
            "updated": event.get("updated"),
            "start": event.get("start", {}).get("dateTime"),
            "end": event.get("end", {}).get("dateTime"),
            "timeZone": event.get("start", {}).get("timeZone"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/calendar/events/{event_id}")
async def update_calendar_event(
    event_id: str,
    update_data: CalendarEventUpdate,
    access_token: str = Depends(get_access_token),
):
    """
    Update a calendar event using PUT method.

    The request body should contain the fields to update, including start and end times as nested objects.
    Example:
    ```json
    {
      "start": {
        "dateTime": "2025-09-21T7:30:00+08:00",
        "timeZone": "Asia/Kuala_Lumpur"
      },
      "end": {
        "dateTime": "2025-09-21T9:00:00+08:00",
        "timeZone": "Asia/Kuala_Lumpur"
      },
      "summary": "Testing"
    }
    ```
    """
    try:
        service = build("calendar", "v3", credentials=access_token)

        # Convert Pydantic model to dictionary and remove None values
        update_dict = {
            k: v
            for k, v in update_data.dict(exclude_unset=True).items()
            if v is not None
        }

        # Call the Calendar API with the dictionary
        updated_event = (
            service.events()
            .update(
                calendarId="primary",
                eventId=event_id,
                body=update_dict,
            )
            .execute()
        )

        # Return a simplified response
        return updated_event
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
