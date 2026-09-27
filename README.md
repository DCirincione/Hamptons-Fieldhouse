# Hamptons Fieldhouse

FastAPI starter with Supabase and native Vercel deployment support. Requires Python 3.13.

## Local development

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

- Homepage: http://localhost:8000
- Interactive API docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/health

The starter runs without Supabase credentials. Add your project's URL and publishable
key (or legacy anon key) to `.env` when you are ready to use the database.
Keep row level security enabled and add policies for the data your API should access.
User authentication and sports/program database tables are not scaffolded yet.

## Website styles and pages

Home (`/`) and About Us (`/about`) extend `app/web/templates/base.html`, which
loads the shared stylesheets for every page:

- `app/web/assets/global.css`: brand colors and font variables, Anton headings,
  DM Sans body text, and the Georgia accent font.
- `app/web/assets/styles.css`: shared components, page layouts, and responsive rules.

New pages should extend `base.html` and use the existing CSS variables instead of
hard-coded colors or fonts. Use semantic heading elements to inherit Anton.

## Add routes

Create route modules in `app/routes/` and register their routers in `app/main.py`.
For database routes, inject the Supabase client:

```python
from fastapi import APIRouter, Depends
from supabase import Client

from app.dependencies import get_supabase

router = APIRouter(prefix="/items", tags=["items"])

@router.get("")
def list_items(db: Client = Depends(get_supabase)):
    return db.table("items").select("*").limit(100).execute().data
```

This example requires an `items` table and an appropriate select policy in Supabase.
Use regular `def` routes with this synchronous client. Requests use the configured
project key; authenticated user tokens are not automatically forwarded to Supabase.

## Deploy to Vercel

1. Push this repository and import it as a new Vercel project.
2. Use the repository root as the Root Directory and the FastAPI framework preset.
   Keep the default build settings. Vercel discovers `app/main.py` and installs
   `requirements.txt`; no custom routing configuration is needed.
3. Add `SUPABASE_URL`, `SUPABASE_KEY`, and `CORS_ORIGINS` in Vercel's environment
   settings. Set `CORS_ORIGINS` to a JSON array containing your frontend's exact
   origin, such as `["https://your-site.com"]`.
4. Deploy, then visit `/docs` and `/api/health` on the deployment URL.

Environment files are ignored by Git. Vercel needs the variables set in its dashboard;
it will not receive your local `.env`.

References: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi)
and [Supabase Python client](https://supabase.com/docs/reference/python/initializing).

## Contact form

`/contact` posts First Name, Last Name, Phone Number, Email, and Message to
`/api/contact-messages`. Run `supabase/migrations/202609260002_contact_messages.sql`
in your Supabase SQL Editor to create the `contact_messages` table and its
insert-only public policy. Your existing `SUPABASE_URL` and publishable
`SUPABASE_KEY` are used server-side. Messages can be viewed in the Supabase dashboard;
public users cannot read them. The form reports success only after storage succeeds.
The migration has not been applied automatically; database tests use a mock client.

### Shared content cards

Wrap major content groups on all new pages with `class="card"` (or `panel`).
The global stylesheet provides the same navy-tinted border, rounded corners,
responsive padding, and soft shadow used on Home, About Us, and Contact.
Use `card-inset` for smaller grouped details within a card. Adjust the shared
`--border-card`, `--shadow-card`, `--padding-card`, and radius variables in
`global.css` to update the treatment site-wide.

Use `page-heading` for page titles and subtitles: these introductions are compact,
unboxed, and aligned with the content container. Reserve `card` for content groups.

## Book & Register

`/space-rentals` contains field rentals, camps and clinics, and both birthday
packages. Pricing and scheduling not yet supplied are shown as TBD. The booking
buttons currently open a preview with phone contact; they do not confirm a booking.

Apply `supabase/migrations/202609260003_bookings.sql` in Supabase SQL Editor to
store the catalog and prepare the private booking tables. The page reads published
offerings once that setup is complete and otherwise uses `app/data/offerings.json`
for the layout preview. See [booking setup](docs/bookings.md) for the database
structure and the remaining requirements for immediate confirmation.
