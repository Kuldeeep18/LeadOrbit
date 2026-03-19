# Lime

Current branding note: the repo and backend still use `Lime` in a few places, but the frontend UI is mostly branded as `LeadOrbit`.

Lime is a multi-tenant outbound outreach MVP built with Django REST Framework and a static HTML/JavaScript frontend. The implemented code supports organization signup, JWT auth, CSV lead import, campaign building, lead enrollment, Gmail sender connection, AI-assisted email drafting, webhook-based engagement tracking, and analytics pages.

This README is based on the current codebase, not the older planning documents in the repo root.

## What Works Today

- JWT auth with organization creation during signup
- Tenant-scoped users, leads, campaigns, and connected sender accounts
- CSV lead import with flexible column aliases and background task support
- Campaign builder with sequence editing, lead selection, sender selection, and launch flow
- Email sending through Gmail API when a Google account is connected
- SMS and call execution through Twilio when credentials are configured
- Open/reply/click/bounce tracking through the webhook endpoint
- AI draft generation through OpenRouter, with fallback draft generation when no API key is set
- Per-lead merge tag replacement, with Gemini-based send-time personalization when configured
- Dashboard and analytics pages backed by API data
- Celery tasks for CSV import, campaign processing, and reply polling

Execution status by step type:

- Fully implemented: `EMAIL`, `SMS`, `CALL`, `WAIT`, `CONDITION_OPEN`, `CONDITION_REPLY`, `CONDITION_CLICK`
- Builder-visible but currently placeholder/auto-advance steps: `WHATSAPP`, `LINKEDIN`, `MANUAL`

## Stack

- Backend: Django 5, Django REST Framework, Simple JWT, Celery, `django-cors-headers`
- Frontend: static HTML pages, ES modules, Bootstrap 5, Chart.js
- Database: SQLite by default at `backend/db.sqlite3`
- Integrations: Google OAuth/Gmail API, OpenRouter, Gemini, Twilio
- Python target: `3.11.9` via [`runtime.txt`](runtime.txt)

## Repo Layout

```text
backend/
  manage.py
  backend/              # active Django project package used by manage.py
  campaigns/            # campaign models, serializers, tasks, Gmail/Twilio/AI integrations
  leads/                # lead models, CSV import task, lead/tag API
  tenants/              # organizations, tenant middleware, security middleware
  users/                # custom user model, registration, profile/JWT auth
  config/               # older scaffold package; not the active settings module

frontend/
  *.html                # active static product screens
  api.js                # API base URL + auth token helpers
  main.js               # shared auth bootstrapping/logout handling
  theme.css             # shared dashboard styling
  src/                  # leftover Vite starter files; not used by the live UI

outreach_frontend/      # currently empty
*.md                    # product and architecture docs from earlier phases
```

## Local Setup

### 1. Create a virtual environment and install dependencies

```sh
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Create `backend/.env`

The backend reads environment variables from `backend/.env`.

```env
DEBUG=True
SECRET_KEY=change-me
BACKEND_BASE_URL=http://127.0.0.1:8000
FRONTEND_BASE_URL=http://127.0.0.1:8080

CELERY_TASK_ALWAYS_EAGER=true
CELERY_BROKER_URL=redis://localhost:6379/0
ENABLE_AUTO_REPLY_DETECTION=false
LAUNCH_IMMEDIATE_PASSES=1

OPENROUTER_API_KEY=
OPENROUTER_MODEL=mistralai/mistral-nemo
OPENROUTER_APP_URL=http://127.0.0.1:8080
OPENROUTER_APP_NAME=Lime Campaign Builder

GEMINI_API_KEY=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
```

### 3. Run migrations

```sh
python backend/manage.py migrate
```

### 4. Start the backend

```sh
cd backend
python manage.py runserver 8000
```

### 5. Serve the frontend

In a second terminal:

```sh
cd frontend
python -m http.server 8080
```

Open `http://127.0.0.1:8080/login.html`.

## Background Jobs

In local development, campaign processing and CSV import work without Redis because `CELERY_TASK_ALWAYS_EAGER=true` by default when `DEBUG=True`.

If you want true async/background execution:

1. Start Redis.
2. Set `CELERY_TASK_ALWAYS_EAGER=false` in `backend/.env`.
3. Run the Celery worker and beat scheduler:

```sh
cd backend
celery -A backend worker -l info
celery -A backend beat -l info
```

Reply polling only runs when `ENABLE_AUTO_REPLY_DETECTION=true`.

## Frontend Behavior

- The active frontend is the static `frontend/*.html` app. There is no active Node build step for the current UI.
- [`frontend/api.js`](frontend/api.js) defaults to `http://127.0.0.1:8000/api/v1` on localhost and the deployed Render API elsewhere.
- You can override the API base URL in the browser:

```js
localStorage.setItem('api_base_url', 'http://127.0.0.1:8000/api/v1');
```

Main screens:

- `login.html`
- `register.html`
- `dashboard.html`
- `leads.html`
- `campaigns.html`
- `campaign-builder.html`
- `analytics.html`
- `settings.html`

## API Surface

Core endpoints exposed by the current backend:

- `POST /api/v1/auth/register/`
- `GET/PATCH /api/v1/auth/me/`
- `POST /api/v1/token/`
- `POST /api/v1/token/refresh/`
- `GET/POST /api/v1/leads/`
- `POST /api/v1/leads/import_csv/`
- `GET/POST/PATCH/DELETE /api/v1/campaigns/`
- `POST /api/v1/campaigns/{id}/enroll/`
- `POST /api/v1/campaigns/{id}/launch/`
- `POST /api/v1/campaigns/ai-generate/`
- `GET /api/v1/analytics/dashboard/`
- `POST /api/v1/webhooks/email/`
- `GET /api/v1/connected-accounts/`
- `GET /api/v1/auth/google/login`
- `GET /api/v1/auth/google/callback`

## Testing

Run the backend test suite from `backend/`:

```sh
python manage.py test
```

Current repo state: `27` backend tests pass. The suite covers auth/profile updates, lead import, tenant isolation, campaign creation, campaign launch, non-email flow handling, conditional branching, connected-account ownership rules, reply polling, and AI fallback behavior.

## Current Caveats

- Branding is inconsistent: the UI mostly says `LeadOrbit`, while parts of the backend and settings still say `Lime`.
- The settings page shows a Gemini API key field, but it is not persisted from the UI. AI credentials are read from `backend/.env`.
- The danger-zone buttons in `settings.html` are presentational only right now.
- [`frontend/src`](frontend/src) and [`backend/config`](backend/config) look like leftover scaffold code and are not part of the main runtime path.
- Some endpoints are still MVP-grade and should be hardened before a production multi-tenant deployment. In particular, analytics currently uses unscoped aggregate queries, and a few utility endpoints are intentionally permissive.
- The root markdown docs describe product intent and planning. The codebase is the source of truth for current behavior.

## Integration Notes

- Gmail sending requires valid Google OAuth client credentials and a connected account from the Settings page.
- SMS and call steps require Twilio credentials and leads with phone numbers.
- If no AI credentials are configured, the campaign builder AI composer still returns a deterministic fallback draft instead of failing hard.
