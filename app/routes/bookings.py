"""Availability and reservations. PostgreSQL owns prices and conflict checks."""
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from supabase import Client, ClientOptions, create_client

from app.config import Settings, get_settings
from app.auth import require_staff, verified_customer
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
    payment_method: Literal["venmo", "cash", "other", "square"]
    payment_plan: Literal["one_session", "all_sessions"] = "one_session"
    additional_dates: list[date] = Field(default_factory=list, max_length=29)
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
        if code == 'P0001':
            raise HTTPException(409, 'A Square payment is processing. Check payment status before changing this booking.') from None
        raise HTTPException(503, "Online booking is temporarily unavailable. Please call 631-278-4374.") from None
    except HTTPError:
        raise HTTPException(503, "We couldn’t reach the booking service. Please retry with the same details.") from None


@router.get("/availability")
def availability(response: Response, service: Service, month: date = Query(...), db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    return rpc(db, "booking_availability", {"p_slug": service, "p_month": month.replace(day=1).isoformat()})


@router.post("", status_code=201)
def reserve(data: Reservation, user=Depends(verified_customer), db: Client = Depends(get_booking_db)):
    start = data.starts_at.astimezone(ZoneInfo("America/New_York"))
    dates = [start.date(), *data.additional_dates]
    if len(set(dates)) != len(dates):
        raise HTTPException(422, "Choose each booking date only once.")
    if any(day < start.date() or day > start.date() + timedelta(days=365) for day in dates):
        raise HTTPException(422, "Choose additional dates on or after your first booking, within the booking window.")
    dates.sort()
    count = len(dates)
    payload = data.model_dump(mode="json", exclude={"additional_dates"})
    # Existing reservation RPCs accept manual methods. A Square choice still
    # creates unpaid pending holds; only the verified payment RPC approves them.
    if data.payment_method == 'square':
        payload['payment_method'] = 'other'
        payload['requested_payment_method'] = 'square'
    # Identity is taken from the verified session, never a customer-supplied ID or email.
    payload["email"] = user.email
    payload["payment_plan"] = data.payment_plan if count > 1 else "one_session"
    payload["initial_payment_cents"] = data.expected_total_cents * (count if payload["payment_plan"] == "all_sessions" else 1)
    payload["session_count"] = count
    payload["occurrences"] = [
        {"starts_at": datetime.combine(day, start.time(), start.tzinfo).isoformat(),
         "request_id": str(uuid5(data.request_id, day.isoformat()))} for day in dates
    ]
    try:
        return rpc(db, "reserve_customer_bookings", {"p_user_id": str(user.id), "p_request": payload})
    except HTTPException as exc:
        if exc.status_code == 409 and count > 1:
            raise HTTPException(409, "A time is unavailable or a price has changed. No bookings were added. Refresh availability or choose different dates.") from None
        raise


@router.get("/mine")
def my_bookings(response: Response, view: Literal["upcoming", "history"] = "upcoming",
                offset: int = Query(0, ge=0), user=Depends(verified_customer), db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    return rpc(db, "customer_bookings", {"p_user_id": str(user.id), "p_view": view, "p_offset": offset})


@router.post("/mine/{booking_id}/cancel")
def cancel_my_booking(booking_id: UUID, user=Depends(verified_customer), db: Client = Depends(get_booking_db)):
    try:
        # Filter ownership and eligibility in the write itself. The database trigger
        # releases every resource for this booking in the same transaction.
        rows = db.table("bookings").update({"status": "cancelled"}).eq(
            "id", str(booking_id)
        ).eq("customer_user_id", str(user.id)).in_("status", ["pending", "confirmed"]).gt(
            "starts_at", datetime.now(timezone.utc).isoformat()
        ).execute().data
    except APIError as exc:
        if exc.code == 'P0001':
            raise HTTPException(409, 'A Square payment is processing. Use Check payment status before cancelling.') from None
        raise HTTPException(503, "Could not cancel your booking. Please refresh and try again.") from None
    except HTTPError:
        raise HTTPException(503, "Could not cancel your booking. Please refresh and try again.") from None
    if not rows:
        raise HTTPException(404, "No upcoming booking available to cancel. Refresh your bookings to check its status.")
    return {"status": "cancelled"}


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["approve", "cancel", "approve_paid", "mark_paid"]


@router.get("/staff", dependencies=[Depends(require_staff)])
def staff_bookings(response: Response, month: date | None = None, db: Client = Depends(get_booking_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        query = db.table("bookings").select(
            "id,first_name,last_name,email,phone_number,starts_at,ends_at,party_size,notes,"
            "status,customer_request_id,total_price_cents,payment_method,payment_status,own_food,created_at,request_payload,"
            "offerings(name),booking_line_items(quantity,booking_extras(name))"
        ).in_("status", ["pending", "confirmed"]).order("starts_at").order("id")
        if month:
            first = month.replace(day=1)
            following = (first + timedelta(days=32)).replace(day=1)
            ny = ZoneInfo("America/New_York")
            query = query.gte("starts_at", datetime(first.year, first.month, 1, tzinfo=ny).isoformat()).lt(
                "starts_at", datetime(following.year, following.month, 1, tzinfo=ny).isoformat())
            bookings = []
            offset = 0
            while True:
                rows = query.range(offset, offset + 499).execute().data
                bookings.extend(rows)
                if len(rows) < 500:
                    break
                offset += 500
        else:
            bookings = query.limit(500).execute().data
        for booking in bookings:
            saved = booking.pop("request_payload", None) or {}
            booking["payment_plan"] = saved.get("payment_plan")
            booking["initial_payment_cents"] = saved.get("initial_payment_cents")
            booking["session_count"] = saved.get("session_count", 1)
        return bookings
    except (APIError, HTTPError):
        raise HTTPException(503, "Could not load bookings. Please retry.") from None


@router.post("/staff/{booking_id}", dependencies=[Depends(require_staff)])
def review_booking(booking_id: UUID, data: Review, db: Client = Depends(get_booking_db)):
    if data.action in ('approve_paid', 'mark_paid'):
        changes = {'payment_status': 'paid'}
        if data.action == 'approve_paid':
            changes['status'] = 'confirmed'
        try:
            # Record money already received manually. Never synthesize a Square
            # payment or overwrite a refunded/cancelled booking. One atomic write
            # prevents confirmation from succeeding without the payment update.
            rows = db.table('bookings').update(changes).eq('id', str(booking_id)).eq(
                'status', 'pending' if data.action == 'approve_paid' else 'confirmed'
            ).eq('payment_status', 'unpaid').in_(
                'payment_method', ['venmo', 'cash', 'other']
            ).execute().data
        except APIError as exc:
            if exc.code == 'P0001':
                raise HTTPException(409, 'A Square payment is processing. Check payment status before recording a manual payment.') from None
            raise HTTPException(503, 'Could not record payment. Refresh and try again.') from None
        except HTTPError:
            raise HTTPException(503, 'Could not record payment. Refresh and try again.') from None
        if not rows:
            raise HTTPException(409, 'This booking has changed or is not eligible for manual payment. Refresh to check its status.')
        return {'status': rows[0]['status'], 'payment_status': rows[0]['payment_status']}
    return rpc(db, "review_booking", {"p_id": str(booking_id), "p_action": data.action})
