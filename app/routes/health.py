from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Application liveness; does not query Supabase."""
    return {"status": "ok"}
