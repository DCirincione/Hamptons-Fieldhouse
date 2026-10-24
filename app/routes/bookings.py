"""Availability and reservations. PostgreSQL owns prices and conflict checks."""
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator
from supabase import Client, ClientOptions, create_client
from storage3.exceptions import StorageApiError

from app.config import Settings, get_settings
from app.auth import require_staff, verified_customer
from app.routes.contact import ContactMessage
from app.routes.gallery import BUCKET as IMAGE_BUCKET, decode_image

router = APIRouter(prefix="/bookings", tags=["bookings"])
Service = Annotated[str, StringConstraints(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
BookingExtra = Literal["additional-child", "pizza-with-toppings"]
BookingResource = Literal["field", "backspace", "party-area"]


def offering_schema_error(exc: APIError) -> HTTPException:
    if exc.code in ("PGRST204", "PGRST205", "42P01", "42703"):
        return HTTPException(503, "Apply or rerun scripts/sql/dynamic_booking_offerings.sql in Supabase to enable camps, clinics, and service management.")
    return HTTPException(503, "Could not save service settings. Refresh and try again.")


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


class ProgramPriceOption(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    price_cents: int = Field(gt=0, le=10_000_000, strict=True)


class ProgramData(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    flyer_url: str = Field(default="", max_length=500)
    flyer_storage_path: str = Field(default="", max_length=300)
    age_range: str = Field(default="", max_length=100)
    sessions: list[str] = Field(default_factory=list, max_length=12)
    activities: list[str] = Field(default_factory=list, max_length=20)
    price_options: list[ProgramPriceOption] = Field(default_factory=list, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("sessions", "activities", "notes")
    @classmethod
    def clean_program_lines(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 240 for value in cleaned):
            raise ValueError("Program details must be 240 characters or fewer per line.")
        return cleaned

    @field_validator("flyer_url")
    @classmethod
    def safe_program_urls(cls, value: str) -> str:
        if value and not value.startswith(("https://", "http://")):
            raise ValueError("Use a complete http:// or https:// URL.")
        return value


class FlyerUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_data: str = Field(max_length=6_000_000)


class OfferingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=1000)
    details: list[str] = Field(max_length=16)
    price_cents: int | None = Field(ge=0, le=10_000_000, strict=True)
    duration_minutes: int = Field(ge=15, le=720, strict=True)
    capacity: int | None = Field(default=None, ge=1, le=500, strict=True)
    published: bool
    sort_order: int = Field(ge=0, le=10000, strict=True)
    own_food_discount_cents: int = Field(default=0, ge=0, le=1_000_000, strict=True)
    resources: list[BookingResource] = Field(default_factory=list, max_length=3)
    program_data: ProgramData = Field(default_factory=ProgramData)

    @field_validator("details")
    @classmethod
    def clean_details(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 300 for value in cleaned):
            raise ValueError("Each service detail must be 300 characters or fewer.")
        return cleaned

    @field_validator("resources")
    @classmethod
    def unique_resources(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Choose each booking space only once.")
        return values


class BookingExtraUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_price_cents: int = Field(ge=0, le=1_000_000, strict=True)


class OfferingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    slug: Service
    category: Literal["field_rental", "birthday", "camp", "clinic"]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=1000)
    details: list[str] = Field(default_factory=list, max_length=16)
    price_cents: int | None = Field(default=None, ge=0, le=10_000_000, strict=True)
    duration_minutes: int = Field(default=60, ge=15, le=720, strict=True)
    capacity: int | None = Field(default=None, ge=1, le=500, strict=True)
    published: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000, strict=True)
    own_food_discount_cents: int = Field(default=0, ge=0, le=1_000_000, strict=True)
    resources: list[BookingResource] = Field(default_factory=list, max_length=3)
    program_data: ProgramData = Field(default_factory=ProgramData)

    @field_validator("details")
    @classmethod
    def clean_details(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if any(len(value) > 300 for value in cleaned):
            raise ValueError("Each service detail must be 300 characters or fewer.")
        return cleaned

    @field_validator("resources")
    @classmethod
    def unique_resources(cls, values: list[str]):
        if len(set(values)) != len(values):
            raise ValueError("Choose each booking space only once.")
        return values


class OfferingReorder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slugs: list[Service] = Field(min_length=1, max_length=100)

    @field_validator("slugs")
    @classmethod
    def unique_slugs(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Each service can only appear once in the new order.")
        return values


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


@router.get("/staff/offerings", dependencies=[Depends(require_staff)])
def staff_offerings(db: Client = Depends(get_booking_db)):
    try:
        offerings = db.table("offerings").select(
            "id,slug,category,name,description,details,price_cents,duration_minutes,capacity,published,sort_order,program_data"
        ).eq("archived", False).order("sort_order").execute().data
        rules = db.table("booking_rules").select(
            "offering_id,own_food_discount_cents,duration_minutes"
        ).execute().data
        mappings = db.table("booking_offering_resources").select(
            "offering_id,resource"
        ).execute().data
    except APIError as exc:
        raise offering_schema_error(exc) from None
    except HTTPError:
        raise HTTPException(503, "Could not load service settings.") from None
    rules_by_offering = {row["offering_id"]: row for row in rules}
    resources_by_offering: dict[str, list[str]] = {}
    for mapping in mappings:
        resources_by_offering.setdefault(mapping["offering_id"], []).append(mapping["resource"])
    for offering in offerings:
        rule = rules_by_offering.get(offering["id"], {})
        offering["own_food_discount_cents"] = rule.get("own_food_discount_cents", 0)
        offering["duration_minutes"] = rule.get("duration_minutes", offering.get("duration_minutes") or 60)
        offering["resources"] = resources_by_offering.get(offering["id"], [])
    return offerings


@router.put("/staff/offerings/{slug}", dependencies=[Depends(require_staff)])
def update_staff_offering(slug: Service, data: OfferingUpdate, db: Client = Depends(get_booking_db)):
    try:
        rows = db.table("offerings").select("id,category").eq("slug", slug).limit(1).execute().data
        if not rows:
            raise HTTPException(404, "That service could not be found.")
        offering_id = rows[0]["id"]
        category = rows[0]["category"]
        if category == "field_rental" and not data.resources:
            raise HTTPException(422, "Choose at least one booking space for a field rental.")
        if category == "field_rental" and data.price_cents is None:
            raise HTTPException(422, "Enter a price for a field rental.")
        if category == "birthday" and (data.price_cents is None or data.capacity is None or data.duration_minutes <= 60):
            raise HTTPException(422, "Birthday packages need a price, included capacity, and a duration longer than 60 minutes.")
        values = data.model_dump(exclude={"own_food_discount_cents", "resources"})
        db.table("offerings").update(values).eq("id", offering_id).execute()
        if category not in ("camp", "clinic", "event"):
            db.table("booking_rules").update({
                "duration_minutes": data.duration_minutes,
                "own_food_discount_cents": data.own_food_discount_cents,
            }).eq("offering_id", offering_id).execute()
            if category == "field_rental":
                db.table("booking_offering_resources").delete().eq("offering_id", offering_id).execute()
                if data.resources:
                    db.table("booking_offering_resources").insert([
                        {"offering_id": offering_id, "resource": resource}
                        for resource in data.resources
                    ]).execute()
        return {"slug": slug, "saved": True}
    except HTTPException:
        raise
    except APIError as exc:
        raise offering_schema_error(exc) from None
    except HTTPError:
        raise HTTPException(503, "Could not reach the booking database. Refresh and try again.") from None


@router.put("/staff/offerings-order", dependencies=[Depends(require_staff)])
def reorder_staff_offerings(data: OfferingReorder, db: Client = Depends(get_booking_db)):
    try:
        rows = db.table("offerings").select("slug,category").in_("slug", data.slugs).eq("archived", False).execute().data
        if len(rows) != len(data.slugs):
            raise HTTPException(404, "One or more services could not be found. Refresh and try again.")
        if len({row["category"] for row in rows}) != 1:
            raise HTTPException(422, "Services can only be reordered within their own section.")
        for index, slug in enumerate(data.slugs, start=1):
            db.table("offerings").update({"sort_order": index * 10}).eq("slug", slug).eq("archived", False).execute()
        return {"saved": True}
    except HTTPException:
        raise
    except APIError as exc:
        raise offering_schema_error(exc) from None
    except HTTPError:
        raise HTTPException(503, "Could not reach the booking database. Refresh and try again.") from None


@router.post("/staff/offerings", dependencies=[Depends(require_staff)], status_code=201)
def create_staff_offering(data: OfferingCreate, db: Client = Depends(get_booking_db)):
    if data.category in ("field_rental", "birthday") and data.price_cents is None:
        raise HTTPException(422, "Enter a price for this bookable service.")
    if data.category == "field_rental" and not data.resources:
        raise HTTPException(422, "Choose at least one booking space for a field rental.")
    if data.category == "birthday" and (data.capacity is None or data.duration_minutes <= 60):
        raise HTTPException(422, "Birthday packages need an included capacity and a duration longer than the 60-minute field session.")
    try:
        created_rows = db.table("offerings").insert({
            "slug": data.slug, "category": data.category, "name": data.name,
            "description": data.description, "details": data.details,
            "program_data": data.program_data.model_dump(),
            "price_cents": data.price_cents if data.category in ("field_rental", "birthday") else None,
            "duration_minutes": data.duration_minutes, "capacity": data.capacity,
            "published": data.published, "sort_order": data.sort_order, "archived": False,
        }).select("id,slug").execute().data
        if not created_rows:
            raise HTTPException(503, "The service was not returned after creation. Refresh and try again.")
        offering = created_rows[0]
        if data.category in ("field_rental", "birthday"):
            db.table("booking_rules").insert({
                "offering_id": offering["id"], "duration_minutes": data.duration_minutes,
                "own_food_discount_cents": data.own_food_discount_cents,
            }).execute()
            if data.category == "birthday":
                mappings = [
                    {"offering_id": offering["id"], "resource": "field", "starts_after_minutes": 0, "ends_after_minutes": 60},
                    {"offering_id": offering["id"], "resource": "party-area", "starts_after_minutes": 60, "ends_after_minutes": None},
                ]
            else:
                mappings = [{"offering_id": offering["id"], "resource": resource} for resource in data.resources]
            db.table("booking_offering_resources").insert(mappings).execute()
        return offering
    except APIError as exc:
        if exc.code in ("PGRST204", "PGRST205", "42P01", "42703"):
            raise offering_schema_error(exc) from None
        if exc.code in ("23505", "409"):
            raise HTTPException(409, "That service ID already exists. Choose another ID.") from None
        raise HTTPException(503, "Could not create this service. Refresh and try again.") from None
    except HTTPError:
        raise HTTPException(503, "Could not reach the booking database. Refresh and try again.") from None


@router.post("/staff/offerings/{slug}/flyer", dependencies=[Depends(require_staff)])
def upload_program_flyer(slug: Service, data: FlyerUpload, db: Client = Depends(get_booking_db)):
    image, extension, content_type = decode_image(data.image_data)
    path = f"program-flyers/{slug}-{uuid4()}.{extension}"
    try:
        rows = db.table("offerings").select("category,program_data").eq("slug", slug).limit(1).execute().data
        if not rows:
            raise HTTPException(404, "That program could not be found.")
        if rows[0]["category"] not in ("camp", "clinic", "event"):
            raise HTTPException(422, "Flyers can only be added to camps and clinics.")
        db.storage.from_(IMAGE_BUCKET).upload(path, image, {"content-type": content_type, "upsert": "false"})
        url = db.storage.from_(IMAGE_BUCKET).get_public_url(path)
        program_data = rows[0].get("program_data") or {}
        old_path = program_data.get("flyer_storage_path")
        program_data.update({"flyer_url": url, "flyer_storage_path": path})
        db.table("offerings").update({"program_data": program_data}).eq("slug", slug).execute()
        if old_path and old_path.startswith("program-flyers/"):
            try:
                db.storage.from_(IMAGE_BUCKET).remove([old_path])
            except (HTTPError, StorageApiError):
                pass
        return {"flyer_url": url, "flyer_storage_path": path}
    except HTTPException:
        raise
    except (APIError, HTTPError, StorageApiError):
        try:
            db.storage.from_(IMAGE_BUCKET).remove([path])
        except (HTTPError, StorageApiError):
            pass
        raise HTTPException(503, "Could not upload the flyer. Check the image storage setup and try again.") from None


@router.get("/staff/camp-registrations", dependencies=[Depends(require_staff)])
def staff_camp_registrations(db: Client = Depends(get_booking_db)):
    try:
        return db.table("camp_registrations").select(
            "id,created_at,session_label,price_label,amount_cents,guardian_name,guardian_email,guardian_phone,participant_name,participant_grade,status,offerings(name)"
        ).order("created_at", desc=True).limit(200).execute().data
    except APIError as exc:
        raise offering_schema_error(exc) from None
    except HTTPError:
        raise HTTPException(503, "Could not load camp registrations.") from None


@router.delete("/staff/offerings/{slug}", dependencies=[Depends(require_staff)])
def archive_staff_offering(slug: Service, db: Client = Depends(get_booking_db)):
    try:
        rows = db.table("offerings").update({"published": False, "archived": True}).eq(
            "slug", slug
        ).eq("archived", False).select("slug").execute().data
        if not rows:
            raise HTTPException(404, "That service was already removed or could not be found.")
        return {"slug": slug, "archived": True}
    except HTTPException:
        raise
    except APIError as exc:
        raise offering_schema_error(exc) from None
    except HTTPError:
        raise HTTPException(503, "Could not reach the booking database. Refresh and try again.") from None


@router.get("/staff/extras", dependencies=[Depends(require_staff)])
def staff_booking_extras(db: Client = Depends(get_booking_db)):
    try:
        return db.table("booking_extras").select(
            "slug,name,unit_price_cents,published"
        ).in_("slug", ["additional-child", "pizza-with-toppings"]).order("slug").execute().data
    except (APIError, HTTPError):
        raise HTTPException(503, "Could not load party add-on prices.") from None


@router.put("/staff/extras/{slug}", dependencies=[Depends(require_staff)])
def update_staff_booking_extra(slug: BookingExtra, data: BookingExtraUpdate, db: Client = Depends(get_booking_db)):
    try:
        rows = db.table("booking_extras").update({"unit_price_cents": data.unit_price_cents}).eq(
            "slug", slug
        ).select("slug").execute().data
        if not rows:
            raise HTTPException(404, "That party add-on could not be found.")
        return {"slug": slug, "saved": True}
    except HTTPException:
        raise
    except APIError:
        raise HTTPException(503, "Could not save the party add-on price. Refresh and try again.") from None
    except HTTPError:
        raise HTTPException(503, "Could not reach the booking database. Refresh and try again.") from None


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
