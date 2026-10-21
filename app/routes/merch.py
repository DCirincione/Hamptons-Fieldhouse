"""Read-only Printful catalog used by the merchandise page."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response

from app.config import Settings, get_settings

router = APIRouter(prefix="/merch", tags=["merchandise"])
PRINTFUL_API = "https://api.printful.com"
_catalog_cache: tuple[float, list[dict]] = (0, [])


def _headers(settings: Settings) -> dict[str, str]:
    token = settings.printful_api_token.get_secret_value()
    if not token:
        raise HTTPException(503, "Merchandise is being prepared. Please check back soon.")
    headers = {"Authorization": f"Bearer {token}"}
    if settings.printful_store_id:
        headers["X-PF-Store-Id"] = settings.printful_store_id
    return headers


def _request(path: str, headers: dict[str, str]) -> dict:
    try:
        response = httpx.get(f"{PRINTFUL_API}{path}", headers=headers, timeout=12)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Merchandise could not be loaded right now. Please try again shortly.") from None


def _product(product: dict, headers: dict[str, str]) -> dict | None:
    # Square is an ecommerce integration, so its catalog is exposed through
    # Printful's Sync Products API rather than the Manual Order / API endpoint.
    result = _request(f"/sync/products/{product['id']}", headers).get("result", {})
    sync_product = result.get("sync_product", product)
    variants = []
    for variant in result.get("sync_variants", []):
        if variant.get("is_ignored") or variant.get("availability_status") == "discontinued":
            continue
        files = variant.get("files") or []
        # Printful includes both the uploaded artwork ("default") and the
        # selected storefront mockup ("preview"). Prefer the mockup so product
        # cards show the finished item rather than a close-up of the logo file.
        mockups = [item for item in files if item.get("type") == "preview"]
        mockup = next(iter(mockups), None)
        fallback = next((item for item in files if item.get("preview_url") or item.get("thumbnail_url")), None)
        selected = mockup or fallback or {}
        image = selected.get("preview_url") or selected.get("thumbnail_url")
        images = []
        for item in mockups or ([fallback] if fallback else []):
            url = item.get("preview_url") or item.get("thumbnail_url")
            if url and url not in images:
                images.append(url)
        variants.append({
            "id": variant.get("id"), "name": variant.get("name") or "Standard",
            "size": variant.get("size"), "color": variant.get("color"),
            "price": variant.get("retail_price"), "image": image, "images": images,
        })
    if not variants:
        return None
    prices = sorted({float(v["price"]) for v in variants if v.get("price") is not None})
    product_images = []
    for variant in variants:
        for image in variant["images"]:
            if image not in product_images:
                product_images.append(image)
    image = next((v["image"] for v in variants if v["image"]), None) or sync_product.get("thumbnail_url") or product.get("thumbnail_url")
    if image and image not in product_images:
        product_images.insert(0, image)
    return {
        "id": sync_product.get("id", product.get("id")),
        "name": sync_product.get("name") or product.get("name") or "Fieldhouse merchandise",
        "image": image, "images": product_images,
        "variants": variants, "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
    }


def get_merch_catalog(settings: Settings) -> list[dict]:
    global _catalog_cache
    # Validate configuration before consulting the process cache so a server
    # with a removed/invalidated credential never serves a stale catalog.
    headers = _headers(settings)
    cached_at, cached = _catalog_cache
    if cached and monotonic() - cached_at < 300:
        return cached
    products = [item for item in _request("/sync/products?status=synced&limit=100", headers).get("result", []) if not item.get("is_ignored")]
    catalog = []
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(products)))) as pool:
        futures = [pool.submit(_product, item, headers) for item in products]
        for future in as_completed(futures):
            item = future.result()
            if item:
                catalog.append(item)
    catalog.sort(key=lambda item: item["name"].casefold())
    _catalog_cache = (monotonic(), catalog)
    return catalog


@router.get("")
def merch_catalog(response: Response, settings: Settings = Depends(get_settings)):
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return {"products": get_merch_catalog(settings), "checkout_enabled": False}
