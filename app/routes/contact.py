import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from supabase import Client

from app.auth import require_staff
from app.config import Settings, get_settings
from app.dependencies import get_supabase

router = APIRouter(tags=["contact"])
logger = logging.getLogger(__name__)


def get_contact_staff_db(settings: Settings = Depends(get_settings)) -> Client:
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise HTTPException(503, "Contact message management is not configured yet.")
    from supabase import ClientOptions, create_client
    return create_client(settings.supabase_url, key,
                         options=ClientOptions(auto_refresh_token=False, persist_session=False))


class ContactMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=7, max_length=30)
    email: EmailStr = Field(max_length=254)
    message: str = Field(min_length=1, max_length=5000)

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not re.fullmatch(r"\+?[0-9().\s-]+", value):
            raise ValueError("Enter a valid phone number.")
        if not 7 <= len(re.sub(r"\D", "", value)) <= 15:
            raise ValueError("Enter a phone number containing 7 to 15 digits.")
        return value


class ContactReadState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_read: bool


@router.post("/contact-messages", status_code=201)
def send_message(data: ContactMessage, db: Client = Depends(get_supabase)) -> dict[str, str]:
    try:
        db.table("contact_messages").insert(data.model_dump(), returning="minimal").execute()
    except (APIError, HTTPError):
        logger.warning("Contact message storage is unavailable")
        raise HTTPException(
            status_code=503,
            detail="We couldn’t save your message. Please try again or email us directly.",
        ) from None
    return {"message": "Thanks for reaching out! Your message has been received."}


@router.get("/contact-messages/staff", dependencies=[Depends(require_staff)])
def staff_messages(response: Response, db: Client = Depends(get_contact_staff_db)) -> list[dict]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return db.table("contact_messages").select(
            "id,first_name,last_name,phone_number,email,message,created_at,read_at"
        ).order("created_at", desc=True).limit(200).execute().data or []
    except (APIError, HTTPError):
        raise HTTPException(503, "Contact messages could not be loaded. Please retry.") from None


@router.patch("/contact-messages/staff/{message_id}", dependencies=[Depends(require_staff)])
def set_message_read_state(message_id: UUID, state: ContactReadState,
                           db: Client = Depends(get_contact_staff_db)) -> dict:
    try:
        rows = db.table("contact_messages").update({
            "read_at": datetime.now(timezone.utc).isoformat() if state.is_read else None
        }).eq("id", str(message_id)).execute().data
    except (APIError, HTTPError):
        raise HTTPException(503, "The message status could not be updated. Please retry.") from None
    if not rows:
        raise HTTPException(404, "Contact message not found.")
    return rows[0]
