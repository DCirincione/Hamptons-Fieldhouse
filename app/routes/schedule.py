"""Staff-managed closures and repeat-customer time blocks."""
from datetime import date, datetime, time, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from supabase import Client

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
        if not time(6) <= self.start < self.end <= time(23):
            raise ValueError("Blocks must start and end between 6 AM and 11 PM on the same day.")
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
    return rpc(db, "staff_schedule", {"p_month": month.replace(day=1).isoformat()})


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
