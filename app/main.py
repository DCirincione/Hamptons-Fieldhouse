from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.auth import get_auth_client, current_user, is_admin
from app.routes.accounts import router as accounts_router
from app.routes.health import router as health_router
from app.routes.contact import router as contact_router
from app.routes.schedule import router as schedule_router
from app.routes.bookings import router as bookings_router
from app.routes.rentals import get_rental_catalog

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(accounts_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(contact_router, prefix="/api")
app.include_router(schedule_router, prefix="/api")
app.include_router(bookings_router, prefix="/api")
web_directory = Path(__file__).resolve().parent / "web"
app.mount("/assets", StaticFiles(directory=web_directory / "assets"), name="assets")
templates = Jinja2Templates(directory=web_directory / "templates")


@app.get("/", include_in_schema=False)
def homepage(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"title": "Home"},
    )


@app.get("/about", include_in_schema=False)
def about(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={"title": "About Us"},
    )


@app.get("/contact", include_in_schema=False)
def contact(request: Request):
    return templates.TemplateResponse(
        request=request, name="contact.html", context={"title": "Contact"}
    )


@app.get("/space-rentals", include_in_schema=False)
def space_rentals(request: Request):
    offerings = get_rental_catalog()
    return templates.TemplateResponse(
        request=request, name="space_rentals.html",
        context={
            "title": "Book & Register",
            "rentals": [o for o in offerings if o["category"] == "field_rental"],
            "packages": [o for o in offerings if o["category"] == "birthday"],
            "programs": [o for o in offerings if o["category"] in ("camp", "clinic", "event")],
        },
    )


@app.get("/admin/bookings", include_in_schema=False)
def booking_staff(request: Request, db=Depends(get_auth_client)):
    try:
        user = current_user(request, db)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return RedirectResponse('/account?next=admin', status_code=303)
    if not is_admin(user):
        raise HTTPException(403, 'An administrator account is required.')
    return templates.TemplateResponse(
        request=request, name="booking_staff.html", context={"title": "Staff Bookings"},
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


@app.get('/account', include_in_schema=False)
def account(request: Request):
    return templates.TemplateResponse(request=request, name='account.html',
        context={'title': 'Your Account'}, headers={'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow'})
