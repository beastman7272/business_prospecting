# Business Prospecting App

An internal web app for finding and researching local businesses that are good
targets for outbound sales, and identifying the right person to contact at each
one. A Flask dashboard drives a three-stage pipeline:

1. **Discover** businesses in an area (Google Places).
2. **Find contacts** — resolve each business to a target *segment*, then search
   for the people whose roles match what the current searcher should target
   (Brave Search + LLM extraction).
3. **Build a dossier** on a chosen contact — a gate verdict, reach info,
   background, engagement, and low-confidence org inferences (OpenAI).

## Searcher profiles — the core idea

Who you should contact at a business depends on *your* business. A general
contractor wants the facilities decision-maker; an accountant wants the finance
lead; a headshot photographer wants marketing/HR. The app separates two things:

- **Shared, searcher-agnostic foundation** (committed to this repo):
  - `roles.py` — one canonical catalog of job roles (coarse keys + title aliases).
  - `target_segments.py` — each kind of target business and the *complete* roster
    of roles that plausibly exist there.
  - `places_mapping.py` — Google Places type → target segment.
- **A per-searcher profile** (`searcher_profiles/<id>.py`) — for each segment the
  searcher sells to, a *priority-ranked subset* of that segment's roles, plus a
  rationale and search tactics. The effective lookup is
  `(target segment × searcher profile) → ranked roles + rationale + tactics`.

`searcher_profiles/__init__.py` **auto-discovers** whatever profile modules are
present, and `active_profile.py` selects the active one.

### Selecting the active searcher

Set `SEARCHER=<id>` in `.env`. If it's unset and only one profile is present,
that one is used automatically.

```bash
python -c "from searcher_profiles import available_searchers; print(available_searchers())"
```

### Adding a searcher profile

Copy the template and edit it:

```bash
cp searcher_profiles/_example.py searcher_profiles/<your_id>.py
python -c "import roles; print(sorted(roles.ROLES))"            # valid role keys
python -c "import target_segments as t; print(sorted(t.SEGMENTS))"  # valid segments
```

All profile modules are committed and ship with the app. On the hosted version,
set `SHOW_SEARCHER_PICKER=true` so each user picks their profile in the UI.

## Setup

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                # then fill in the values (see below)
flask db upgrade                    # creates instance/prospecting.db
python app.py                       # http://127.0.0.1:5000
```

### Environment (`.env`)

Copy `.env.example` to `.env` and fill in the values below. Each provider gives
you a key from its own dashboard; sign in, create a key, paste it in. Links point
to where the key is issued — check the provider's current docs if a page has
moved.

| Variable | What it's for | Where to get it |
| --- | --- | --- |
| `GOOGLE_PLACES_API_KEY` | Stage 1 business discovery | Google Cloud Console → enable **Places API (New)**, then create an API key. https://console.cloud.google.com/ · docs: https://developers.google.com/maps/documentation/places/web-service |
| `GEMINI_API_KEY` | Stage 2 contact extraction | Google AI Studio → **Get API key**. https://aistudio.google.com/app/apikey |
| `BRAVE_SEARCH_API_KEY` | Stage 2/3 web search | Brave Search API dashboard → subscribe (free tier available), create a key. https://api-dashboard.search.brave.com/ |
| `OPENAI_API_KEY` | Stage 3 dossier LLM | OpenAI platform → **API keys**. https://platform.openai.com/api-keys |
| `SECRET_KEY` | Flask session/CSRF signing key | Generate any long random string: `python -c "import secrets; print(secrets.token_hex(32))"`. Keep it stable (changing it invalidates existing sessions). |
| `FLASK_APP` | Flask entry point | Set to `app:create_app` (not a secret). |
| `FLASK_ENV` | Flask environment | `development` locally (not a secret). |
| `SEARCHER` | Active searcher profile id | An id present in `searcher_profiles/` (e.g. `gc`). Optional if only one profile is present. |

Secrets never belong in git: `.env` and `instance/` (the SQLite DB) are both
gitignored.

## Command-line runner

Run discovery for one business without the web app (`--mock` needs no API keys):

```bash
python run_discovery.py --name "Acme, PC" --city Duluth --state GA --type lawyer --mock
```

## Layout

```
app.py                  Flask app factory
config.py, models.py    config + SQLAlchemy models
blueprints/             web + JSON API routes
services/               Stage 1 intel, discovery orchestration, DB ops
contact_discovery.py    Stage 2: places-type → segment × profile → contacts
contact_dossier.py      Stage 3: per-contact dossier (backend-agnostic scaffold)
dossier_llm_openai.py   Stage 3 OpenAI backend
fetch_and_extract.py    shared page fetch/extract
roles.py                canonical role catalog (shared)
target_segments.py      target segments + role inventories (shared)
places_mapping.py       Google Places type → segment (shared)
searcher_profiles/      per-searcher profiles (base + template committed; rest gitignored)
active_profile.py       selects the active searcher
run_discovery.py        CLI entry point
migrations/             Alembic migrations
```

## Hosted deployment (Railway)

The same code runs locally and on Railway; environment variables decide which.

| | Local | Railway |
| --- | --- | --- |
| `APP_ENV` | unset (development) | `production` |
| Database | SQLite in `instance/` | Postgres via `DATABASE_URL` |
| Server | `python app.py` | `gunicorn main:app` (settings in `gunicorn.conf.py`) |
| `APP_PASSWORD` | unset | optional shared password |

`gunicorn.conf.py` applies database migrations at startup (production only) and
sets a 300s timeout (contact discovery and dossier requests are slow). Required
Railway variables: the four provider keys, `SECRET_KEY`, `APP_ENV=production`,
`SHOW_SEARCHER_PICKER=true`, and `DATABASE_URL=${{Postgres.DATABASE_URL}}`.

Before a release, run migrations against both SQLite and Postgres.

## Notes

- Internal, single-user tool; no auth in v1.
- The pipeline degrades gracefully — a failed track (e.g. org inference) drops
  rather than sinking the whole dossier.
