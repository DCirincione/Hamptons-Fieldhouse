"""Availability and reservations. PostgreSQL owns prices and conflict checks."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from supabase import Client, ClientOptions, create_client

from app.config import Settings, get_settings
from app.auth import require_staff
from app.routes.contact import ContactMessage

router = APIRouter(prefix="/bookings", tags=["bookings"])
Service = Literal["full-field", "speed-agility", "turf-fun-party", "ultimate-field-house-party"]


def get_booking_db(settings: Settings = Depends(get_settings)) -> Client:
    # Never reuse a public/anon key for reservation writes.
    if not settings.supabase_url or not settings.supabase_service_role_key.get_secret_value():
        raise HTTPException(503, "Online booking is not available yet. Please call 631-278-4374.")
    return create_client(
        settings.supabase_url, settings.supabase_service_role_key.get_secret_value(),
        options=ClientOptions(auto_refresh_token=False, persist_session=False, postgrest_client_timeout=10),
    )


class Reservation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    request_id: UUID
    service: Service
    starts_at: datetime
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=254)
    phone_number: str = Field(min_length=7, max_length=30)
    party_size: int = Field(ge=1, le=200, strict=True)
    extra_pizzas: int = Field(default=0, ge=0, le=20, strict=True)
    own_food: bool = False
    payment_method: Literal["venmo", "other"]
    notes: str = Field(default="", max_length=3000)
    expected_total_cents: int = Field(ge=0, strict=True)

    @field_validator("starts_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("Choose a time with a timezone.")
        return value

    @field_validator("phone_number")
    @classmethod
    def phone_valid(cls, value: str) -> str:
        return ContactMessage.validate_phone(value)


def rpc(db: Client, function: str, params: dict):
    try:
        return db.rpc(function, params).execute().data
    except APIError as exc:
        code = exc.code
        if code in ("23P01", "P0002"):
            raise HTTPException(409, "That time is no longer available. Please choose another time.") from None
        if code == "P0003":
            raise HTTPException(409, "The price has changed. Refresh the calendar and review your total.") from None
        if code == "22023":
            raise HTTPException(422, "Please check your booking details and choose an available time.") from None
        raise HTTPException(503, "Online booking is temporarily unavailable. Please call 631-278-4374.") from None
    except HTTPError:
        raise HTTPException(503, "We couldn’t reach the booking service. Please retry with the same details.") from None


@router.get("/availability")
def availability(response: Response, service: Service, month: date = Query(...), db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    return rpc(db, "booking_availability", {"p_slug": service, "p_month": month.replace(day=1).isoformat()})


@router.post("", status_code=201)
def reserve(data: Reservation, db: Client = Depends(get_booking_db)):
    return rpc(db, "reserve_booking", {"p_request": data.model_dump(mode="json")})


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "cancel"]


@router.get("/staff", dependencies=[Depends(require_staff)])
def staff_bookings(response: Response, db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return db.table("bookings").select(
            "id,first_name,last_name,email,phone_number,starts_at,ends_at,party_size,notes,"
            "status,total_price_cents,payment_method,payment_status,own_food,created_at,"
            "offerings(name),booking_line_items(quantity,booking_extras(name))"
        ).in_("status", ["pending", "confirmed"]).order("starts_at").limit(500).execute().data
    except (APIError, HTTPError):
        raise HTTPException(503, "Could not load bookings. Please retry.") from None


@router.post("/staff/{booking_id}", dependencies=[Depends(require_staff)])
def review_booking(booking_id: UUID, data: Review, db: Client = Depends(get_booking_db)):
    return rpc(db, "review_booking", {"p_id": str(booking_id), "p_action": data.action})
