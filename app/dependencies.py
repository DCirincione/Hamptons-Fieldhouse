from fastapi import Depends, HTTPException, status
from supabase import Client, ClientOptions, create_client

from app.config import Settings, get_settings


def get_supabase(settings: Settings = Depends(get_settings)) -> Client:
    """Create a request-scoped client so auth state is never shared across users."""
    if not settings.supabase_url or not settings.supabase_key.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase is not configured. Set SUPABASE_URL and SUPABASE_KEY.",
        )
    return create_client(
        settings.supabase_url,
        settings.supabase_key.get_secret_value(),
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
