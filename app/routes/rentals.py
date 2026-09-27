import json
import logging
from pathlib import Path

from httpx import HTTPError
from postgrest.exceptions import APIError
from supabase import ClientOptions, create_client

from app.config import get_settings

logger = logging.getLogger(__name__)
CATALOG = Path(__file__).resolve().parent.parent / "data" / "offerings.json"


def get_rental_catalog() -> list[dict]:
    """Read published offerings, with the approved layout catalog as a fallback."""
    settings = get_settings()
    if settings.supabase_url and settings.supabase_key.get_secret_value():
        try:
            db = create_client(
                settings.supabase_url,
                settings.supabase_key.get_secret_value(),
                options=ClientOptions(
                    auto_refresh_token=False, persist_session=False,
                    postgrest_client_timeout=3,
                ),
            )
            return db.table("offerings").select(
                "slug,category,name,description,details,price_cents,duration_minutes,capacity,sort_order"
            ).eq("published", True).order("sort_order").execute().data
        except (APIError, HTTPError, ValueError):
            logger.warning("Offerings unavailable; showing the approved layout preview")
    return json.loads(CATALOG.read_text())

