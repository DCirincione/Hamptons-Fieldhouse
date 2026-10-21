"""Public gallery data and staff-only gallery management."""
import base64
import binascii
import re
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from httpx import HTTPError
from postgrest.exceptions import APIError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from storage3.exceptions import StorageApiError
from supabase import Client, ClientOptions, create_client

from app.auth import require_staff
from app.config import Settings, get_settings

router = APIRouter(prefix="/gallery", tags=["gallery"])
BUCKET = "gallery-images"
DATA_URL = re.compile(r"^data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)$")


def get_gallery_db(settings: Settings = Depends(get_settings)) -> Client:
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        raise HTTPException(503, "Gallery management is not configured yet.")
    return create_client(settings.supabase_url, key,
                         options=ClientOptions(auto_refresh_token=False, persist_session=False))


FALLBACK_PHOTOS = [
    "/assets/photos/fieldhouse-turf.jpg", "/assets/photos/A7V08705-HDR-web.jpg",
    "/assets/photos/A7V08706-HDR-web.jpg", "/assets/photos/A7V08727-HDR-web.jpg",
    "/assets/photos/A7V08728-HDR-web.jpg", "/assets/photos/A7V08737-HDR-web.jpg",
    "/assets/photos/A7V08743-HDR-web.jpg", "/assets/photos/A7V08748-HDR-web.jpg",
    "/assets/photos/A7V08753-HDR-web.jpg", "/assets/photos/A7V08758-HDR-web.jpg",
    "/assets/photos/A7V08772-HDR-web.jpg", "/assets/photos/A7V08773-HDR-web.jpg",
    "/assets/photos/A7V08783-HDR-web.jpg", "/assets/photos/A7V08795-HDR-web.jpg",
    "/assets/photos/A7V08796-HDR-web.jpg", "/assets/photos/A7V08802-HDR-web.jpg",
    "/assets/photos/A7V08819-HDR-web.jpg",
]


def fallback_gallery() -> list[dict]:
    return [{"id": f"default-{i}", "image_url": url, "position": i}
            for i, url in enumerate(FALLBACK_PHOTOS, 1)]


def load_gallery_photos(settings: Settings) -> list[dict]:
    key = settings.supabase_service_role_key.get_secret_value()
    if not settings.supabase_url or not key:
        return fallback_gallery()
    try:
        db = create_client(settings.supabase_url, key,
                           options=ClientOptions(auto_refresh_token=False, persist_session=False))
        rows = db.table("gallery_photos").select(
            "id,image_url,position"
        ).order("position").execute().data
        return rows or fallback_gallery()
    except (APIError, HTTPError):
        return fallback_gallery()


class GalleryUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_data: str = Field(max_length=6_000_000)


class GalleryOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_ids: list[UUID] = Field(min_length=1, max_length=100)

    @field_validator("photo_ids")
    @classmethod
    def unique_photo_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Photo IDs must be unique.")
        return value


def decode_image(data_url: str) -> tuple[bytes, str, str]:
    match = DATA_URL.fullmatch(data_url)
    if not match:
        raise HTTPException(422, "Upload a JPEG, PNG, or WebP image.")
    try:
        image = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(422, "The uploaded image could not be read.") from None
    if not image or len(image) > 4_000_000:
        raise HTTPException(413, "The optimized image must be 4 MB or smaller.")
    kind = match.group(1)
    signatures = {"jpeg": image.startswith(b"\xff\xd8\xff"),
                  "png": image.startswith(b"\x89PNG\r\n\x1a\n"),
                  "webp": len(image) > 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP"}
    if not signatures[kind]:
        raise HTTPException(422, "The uploaded file does not match its image type.")
    return image, ("jpg" if kind == "jpeg" else kind), f"image/{kind}"


@router.get("/staff", dependencies=[Depends(require_staff)])
def staff_gallery(response: Response, db: Client = Depends(get_gallery_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return db.table("gallery_photos").select(
            "id,image_url,storage_path,position,created_at"
        ).order("position").execute().data
    except (APIError, HTTPError):
        raise HTTPException(503, "Could not load gallery photos. Check the external database setup and retry.") from None


@router.post("/staff", status_code=201, dependencies=[Depends(require_staff)])
def add_gallery_photo(data: GalleryUpload, db: Client = Depends(get_gallery_db)):
    image, extension, content_type = decode_image(data.image_data)
    path = f"{uuid4()}.{extension}"
    try:
        db.storage.from_(BUCKET).upload(path, image, {"content-type": content_type, "upsert": "false"})
        url = db.storage.from_(BUCKET).get_public_url(path)
        last = db.table("gallery_photos").select("position").order(
            "position", desc=True
        ).limit(1).execute().data
        row = db.table("gallery_photos").insert({
            "image_url": url, "storage_path": path,
            "position": (last[0]["position"] + 1) if last else 1,
        }).execute().data[0]
        return row
    except (APIError, HTTPError, StorageApiError):
        try:
            db.storage.from_(BUCKET).remove([path])
        except (HTTPError, StorageApiError):
            pass
        raise HTTPException(503, "Could not add the photo. Please retry.") from None


@router.put("/staff/order", dependencies=[Depends(require_staff)])
def reorder_gallery_photos(data: GalleryOrder, db: Client = Depends(get_gallery_db)):
    requested_ids = [str(photo_id) for photo_id in data.photo_ids]
    try:
        current = db.table("gallery_photos").select("id").order("position").execute().data
        current_ids = [str(row["id"]) for row in (current or [])]
        if len(requested_ids) != len(current_ids) or set(requested_ids) != set(current_ids):
            raise HTTPException(409, "The gallery changed. Refresh the page and try reordering again.")

        # Move positions out of the active range first so a unique position
        # constraint cannot collide while two neighboring photos trade places.
        for position, photo_id in enumerate(requested_ids, 1):
            db.table("gallery_photos").update({
                "position": 1_000_000 + position
            }).eq("id", photo_id).execute()
        for position, photo_id in enumerate(requested_ids, 1):
            db.table("gallery_photos").update({
                "position": position
            }).eq("id", photo_id).execute()
    except HTTPException:
        raise
    except (APIError, HTTPError):
        raise HTTPException(503, "Could not save the gallery order. Please retry.") from None
    return {"photo_ids": requested_ids}


@router.delete("/staff/{photo_id}", status_code=204, dependencies=[Depends(require_staff)])
def delete_gallery_photo(photo_id: UUID, db: Client = Depends(get_gallery_db)):
    try:
        found = db.table("gallery_photos").select("storage_path").eq(
            "id", str(photo_id)
        ).limit(1).execute().data
        if not found:
            raise HTTPException(404, "This gallery photo no longer exists.")
        db.table("gallery_photos").delete().eq("id", str(photo_id)).execute()
        if found[0].get("storage_path"):
            db.storage.from_(BUCKET).remove([found[0]["storage_path"]])
    except HTTPException:
        raise
    except (APIError, HTTPError, StorageApiError):
        raise HTTPException(503, "Could not remove this photo. Please retry.") from None
    return Response(status_code=204)
