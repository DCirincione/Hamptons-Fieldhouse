from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Hamptons Fieldhouse API"
    supabase_url: str = ""
    supabase_key: SecretStr = SecretStr("")
    supabase_service_role_key: SecretStr = SecretStr("")
    printful_api_token: SecretStr = SecretStr("")
    printful_store_id: str = ""
    square_environment: Literal["sandbox", "production"] = "sandbox"
    square_booking_payments_enabled: bool = False
    square_merch_checkout_enabled: bool = False
    square_merch_shipping_cents: int = 0
    square_sandbox_webhook_signature_key: SecretStr = SecretStr("")
    square_webhook_url: str = ""
    square_sandbox_access_token: SecretStr = SecretStr("")
    square_sandbox_application_id: str = ""
    square_sandbox_location_id: str = ""
    square_production_webhook_signature_key: SecretStr = SecretStr("")
    square_production_access_token: SecretStr = SecretStr("")
    square_production_application_id: str = ""
    square_production_location_id: str = ""
    site_url: str = "http://localhost:8000"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
