import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from supabase import Client

from app.dependencies import get_supabase

router = APIRouter(tags=["contact"])
logger = logging.getLogger(__name__)


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
