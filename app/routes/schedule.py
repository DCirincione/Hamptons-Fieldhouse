"""Staff-managed closures and repeat-customer time blocks."""
import csv

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from supabase import Client
from httpx import HTTPError
from postgrest.exceptions import APIError

from app.routes.bookings import get_booking_db, require_staff, rpc

router = APIRouter(prefix="/bookings/staff/schedule", tags=["staff schedule"], dependencies=[Depends(require_staff)])
NY = ZoneInfo("America/New_York")
Resource = Literal["field", "backspace", "party-area"]


class TimeBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    start: time
    end: time

    @model_validator(mode="after")
    def valid_hours(self):
        if self.start.tzinfo or self.end.tzinfo or self.start.second or self.end.second or self.start.microsecond or self.end.microsecond:
            raise ValueError("Use local Eastern times in whole minutes.")
        if not self.start < self.end:
            raise ValueError("End time must be after start time on the same day.")
        return self


class ScheduleBlock(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    resources: list[Resource] = Field(min_length=1, max_length=3)
    mode: Literal["dates", "daily", "weekly"]
    dates: list[TimeBlock] = Field(default_factory=list, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    start: time | None = None
    end: time | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)

    def occurrences(self, today: date | None = None) -> list[dict]:
        today = today or datetime.now(NY).date()
        if len(set(self.resources)) != len(self.resources):
            raise ValueError("Choose each space only once.")
        blocks = self.dates
        if self.mode != "dates":
            if self.dates or not all((self.start_date, self.end_date, self.start, self.end)):
                raise ValueError("Choose a start date, end date, and time range for repeating blocks.")
            if not today <= self.start_date <= self.end_date <= today + timedelta(days=365):
                raise ValueError("Choose a date range within the next year.")
            if self.mode == "weekly" and (not self.weekdays or any(type(d) is not int or d not in range(7) for d in self.weekdays)):
                raise ValueError("Select the weekdays to repeat.")
            blocks = []
            day = self.start_date
            while day <= self.end_date:
                if self.mode == "daily" or day.weekday() in self.weekdays:
                    blocks.append(TimeBlock(date=day, start=self.start, end=self.end))
                day += timedelta(days=1)
        elif any(value is not None for value in (self.start_date, self.end_date, self.start, self.end)) or self.weekdays:
            raise ValueError("Use individual date rows or a repeating schedule, not both.")
        if not blocks:
            raise ValueError("Choose at least one matching date.")
        result = []
        for block in blocks:
            if not today <= block.date <= today + timedelta(days=365):
                raise ValueError("Choose dates within the next year.")
            for value in (block.start, block.end):
                local = datetime.combine(block.date, value, NY)
                if local.astimezone(timezone.utc).astimezone(NY).replace(tzinfo=None) != local.replace(tzinfo=None):
                    raise ValueError("That local time does not exist because the clocks change. Choose another time.")
            result.append({"starts_at": datetime.combine(block.date, block.start, NY).isoformat(),
                           "ends_at": datetime.combine(block.date, block.end, NY).isoformat()})
        # Reject duplicates/overlapping rows before submitting the entire batch.
        result.sort(key=lambda row: row["starts_at"])
        if any(a["ends_at"] > b["starts_at"] for a, b in zip(result, result[1:])):
            raise ValueError("Some entered time ranges overlap. Adjust them before saving.")
        return result


@router.get("")
def schedule(month: date, response: Response, db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    first = month.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    start = datetime.combine(first, time.min, NY).isoformat()
    end = datetime.combine(following, time.min, NY).isoformat()
    result = []
    try:
        # Read existing slots directly: older installations may not have the
        # staff_schedule RPC or the optional series_id column yet.
        offset = 0
        while True:
            rows = db.table("booking_resource_slots").select(
                "*,bookings(status,first_name,last_name,offerings(name))"
            ).filter("during", "ov", f'["{start}","{end}")').order("id").range(offset, offset + 499).execute().data
            for row in rows:
                starts_at, ends_at = next(csv.reader([row["during"][1:-1]]))
                booking = row.get("bookings") or {}
                offering = booking.get("offerings") or {}
                title = (f"{offering.get('name', 'Booking')} — {booking.get('first_name', '')} {booking.get('last_name', '')}".strip()
                         if row.get("booking_id") else row.get("note", "Blocked time"))
                result.append({"id": row["id"], "resource": row["resource"],
                               "starts_at": starts_at, "ends_at": ends_at,
                               "series_id": row.get("series_id"), "booking_id": row.get("booking_id"),
                               "title": title, "status": booking.get("status", "blocked")})
            if len(rows) < 500:
                break
            offset += 500
        return sorted(result, key=lambda row: (row["starts_at"], row["resource"]))
    except (APIError, HTTPError, ValueError, KeyError, csv.Error):
        raise HTTPException(503, "Could not load reserved times. Refresh the calendar to retry. Opening hours can still be edited.") from None


@router.post("", status_code=201)
def add_blocks(data: ScheduleBlock, db: Client = Depends(get_booking_db)):
    try:
        occurrences = data.occurrences()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    try:
        return rpc(db, "add_schedule_blocks", {"p_request": {
            "request_id": str(data.request_id), "title": data.title,
            "resources": data.resources, "occurrences": occurrences,
        }})
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(409, "One or more times overlap an existing booking or block. Nothing was added. Review the schedule and adjust your dates or times.") from None
        raise


class RemoveBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot_id: UUID
    scope: Literal["occurrence", "series"] = "occurrence"


@router.post("/remove")
def remove_blocks(data: RemoveBlock, db: Client = Depends(get_booking_db)):
    return rpc(db, "remove_schedule_block", {"p_id": str(data.slot_id), "p_series": data.scope == "series"})


class OpeningHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opens: time | None = None
    closes: time | None = None

    @model_validator(mode="after")
    def valid_interval(self):
        if self.opens is None and self.closes is None:
            return self
        if self.opens is None or self.closes is None:
            raise ValueError("Choose opening and closing times on the same day, or mark the day closed.")
        if any(t.tzinfo or t.second or t.microsecond for t in (self.opens, self.closes)):
            raise ValueError("Use Eastern times in whole minutes.")
        if self.opens >= self.closes:
            raise ValueError("Closing time must be after opening time on the same day.")
        return self


class WeeklyHours(OpeningHours):
    weekday: int = Field(ge=0, le=6, strict=True)


class HoursUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: list[WeeklyHours] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def unique_days(self):
        if {day.weekday for day in self.days} != set(range(7)):
            raise ValueError("Include each weekday exactly once.")
        return self


class DateHours(OpeningHours):
    date: date
    reset: bool = False

    @model_validator(mode="after")
    def valid_date(self):
        today = datetime.now(NY).date()
        if not today <= self.date <= today + timedelta(days=365):
            raise ValueError("Choose a date within the next year.")
        if self.reset and (self.opens is not None or self.closes is not None):
            raise ValueError("Reset uses the regular weekly hours; omit custom times.")
        return self


@router.get("/hours")
def opening_hours(response: Response, db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    return rpc(db, "staff_opening_hours", {})


@router.put("/hours")
def update_opening_hours(data: HoursUpdate, db: Client = Depends(get_booking_db)):
    return rpc(db, "set_weekly_opening_hours", {"p_days": data.model_dump(mode="json")["days"]})


@router.put("/hours/date")
def update_date_hours(data: DateHours, db: Client = Depends(get_booking_db)):
    return rpc(db, "set_date_opening_hours", {"p_day": data.model_dump(mode="json")})
