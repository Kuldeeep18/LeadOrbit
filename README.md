# LeadOrbit
![Python](https://img.shields.io/badge/Python-3.11-blue)
![Django](https://img.shields.io/badge/Django-5.0-green)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![LastCommit](https://img.shields.io/github/last-commit/Kuldeeep18/LeadOrbit)
![Stars](https://img.shields.io/github/stars/Kuldeeep18/LeadOrbit)
Current branding note: the active app is branded as `LeadOrbit`; older planning documents in the repo may still mention the original `Lime` name.

LeadOrbit is a multi-tenant outbound outreach MVP built with Django REST Framework and a static HTML/JavaScript frontend. The implemented code supports organization signup, JWT auth, CSV lead import, campaign building, lead enrollment, Gmail sender connection, AI-assisted email drafting, webhook-based engagement tracking, and analytics pages.

This README is based on the current codebase, not the older planning documents in the repo root.

## 📑 Table of Contents
- [LeadOrbit](#leadorbit)
- [What Works Today](#what-works-today)
- [Stack](#stack)
- [Repo Layout](#repo-layout)
- [Local Setup](#local-setup)
- [Deploy for free (Render + Netlify)](#deploy-for-free-render--netlify)
- [Deploy with Docker](#deploy-with-docker)
- [Background Jobs](#background-jobs)
- [Frontend Behavior](#frontend-behavior)
- [API Surface](#api-surface)
- [Testing](#testing)
- [Current Caveats](#current-caveats)
- [Integration Notes](#integration-notes)
- [Contributors](#contributors)

## Code of Conduct

This project adheres to the Contributor Covenant [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to abide by its terms.

## Contributing

... existing contributing content ...

## What Works Today

- JWT auth with organization creation during signup
- Tenant-scoped users, leads, campaigns, and connected sender accounts
- CSV lead import with flexible column aliases and background task support
- Campaign builder with sequence editing, lead selection, sender selection, and launch flow
- Email sending through Gmail API when a Google account is connected
- SMS and call execution through Twilio when credentials are configured
- Open/reply/click/bounce tracking through the webhook endpoint
- Optional send-time AI personalization through a self-hosted Ollama model (no API key) or Gemini. Off by default; emails then go out as written with merge tags filled in
- Per-lead merge tag replacement
- Dashboard and analytics pages backed by API data
- Celery tasks for CSV import, campaign processing, and reply polling

Execution status by step type:

- Fully implemented: `EMAIL`, `SMS`, `CALL`, `WAIT`, `CONDITION_OPEN`, `CONDITION_REPLY`, `CONDITION_CLICK`
- Builder-visible but currently placeholder/auto-advance steps: `WHATSAPP`, `LINKEDIN`, `MANUAL`

## Stack

- Backend: Django 5, Django REST Framework, Simple JWT, Celery, `django-cors-headers`
- Frontend: static HTML pages, ES modules, Bootstrap 5, Chart.js
- Database: SQLite by default at `backend/db.sqlite3`
- AI (optional): Ollama (self-hosted) or Gemini, for send-time personalization
- Integrations: Google OAuth/Gmail API, Twilio
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

AI_PROVIDER=none              # none | ollama | gemini  (send-time personalization)
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:3b

# Only needed when AI_PROVIDER=gemini
GEMINI_API_KEY=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
```

### 3. (Optional) Run a local AI model

Send-time personalization can run on your own machine through [Ollama](https://ollama.com), so no API key or paid service is needed. Set `AI_PROVIDER=ollama`, install Ollama, then:

```sh
ollama pull qwen2.5:3b     # ~2 GB, one-time download
```

Ollama serves the model at `http://127.0.0.1:11434`. If it isn't running, LeadOrbit still works and sends your templates with merge tags filled in. In production, run Ollama on the same server as the backend (or a private box) and point `OLLAMA_BASE_URL` at it.

### 4. Run migrations

```sh
python backend/manage.py migrate
```

### 5. Start the backend

```sh
cd backend
python manage.py runserver 8000
```

### 6. Serve the frontend

In a second terminal:

```sh
cd frontend
python -m http.server 8080
```

Open `http://127.0.0.1:8080/login.html`.

## Deploy for free (Render + Netlify)

The backend runs on Render's free web service, the frontend on Netlify, the database on a free Postgres provider, and a GitHub Actions job replaces the background worker. No credit card or AI service is required (free-tier limits change, so check each provider's current terms).

| Piece | Where | Config in repo |
|---|---|---|
| Backend API | Render free web service | [`render.yaml`](render.yaml) |
| Frontend | Netlify free | [`netlify.toml`](netlify.toml) |
| Database | Free Postgres, e.g. [Neon](https://neon.tech) or [Supabase](https://supabase.com) | `DATABASE_URL` |
| Scheduled sending | GitHub Actions, every 10 min | [`.github/workflows/cron-tick.yml`](.github/workflows/cron-tick.yml) |

1. **Database:** create a free Postgres database and copy its connection string (`postgres://…?sslmode=require`).
2. **Backend:** in Render, choose *New → Blueprint* and pick this repo. Fill in `DATABASE_URL`, `BACKEND_BASE_URL` (e.g. `https://leadorbit.onrender.com`), and `CORS_ALLOWED_ORIGINS` / `FRONTEND_BASE_URL` (your Netlify URL; set these after step 3 if you don't know it yet). `SECRET_KEY`, `MAILBOX_CREDENTIALS_ENCRYPTION_KEY`, `CRON_SECRET` and `WEBHOOK_SECRET` are generated for you. If an email provider sends open/reply/bounce events to `/api/v1/webhooks/email/`, configure it to send `WEBHOOK_SECRET` as the `X-Webhook-Secret` header (or `?token=`).
3. **Frontend:** in Netlify, *Add new site → Import from Git* and pick this repo; `netlify.toml` already sets the folder. Add the environment variable `API_BASE_URL=https://<your-render-service>.onrender.com/api/v1` and deploy.
4. **Scheduler:** in GitHub, *Settings → Secrets and variables → Actions*: add the variable `BACKEND_URL` (your Render URL) and the secret `CRON_SECRET` (copy it from the Render service's environment). Run the *Campaign scheduler tick* workflow once by hand to check it.

What to expect on free plans:
- The free Render service sleeps after ~15 minutes without traffic, and the first request then takes about a minute. The 10-minute scheduler mostly keeps it awake.
- Sequence steps are sent when the scheduler runs, so a "wait 1 day" step can fire up to ~10 minutes late. GitHub may delay scheduled runs at busy times, and it pauses schedules in repos with no activity for 60 days. [cron-job.org](https://cron-job.org) is a free alternative that can call the same URL every minute.
- AI personalization is off (`AI_PROVIDER=none`): emails go out exactly as written, with merge tags filled in.

## Deploy with Docker

One command runs the whole product on any Linux server (or Docker Desktop), including a self-hosted AI model, with no paid APIs:

| Container | Role |
|---|---|
| `web` | Caddy: serves the frontend, proxies `/api`, automatic HTTPS. **The only public container.** |
| `backend` | Django API on gunicorn; runs migrations on start |
| `worker` / `beat` | Celery: sends sequences, imports CSVs, polls replies/bounces |
| `db` / `redis` | Postgres 16 and Redis 7 (private, persistent volumes) |
| `ollama` | Local AI model for send-time personalization (private) |

```sh
cp .env.docker.example .env      # fill in SECRET_KEY, MAILBOX_CREDENTIALS_ENCRYPTION_KEY, POSTGRES_PASSWORD, WEBHOOK_SECRET
docker compose up -d --build     # first start downloads the AI model (~2 GB)
docker compose ps                # everything should be Up / healthy
```

Open `http://<server>/`. For a real domain, set `SITE_ADDRESS=leadorbit.example.com` (plus the matching `PUBLIC_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `BACKEND_BASE_URL`, `FRONTEND_BASE_URL`), point the domain's DNS at the server and open ports 80/443. Caddy fetches a free Let's Encrypt certificate automatically.

**Server sizing:** at least 4 vCPU, 8 GB RAM and 25 GB disk (the Ollama image is ~9 GB). On CPU, a 3B model writes one email in roughly 20–30 s. That's fine for background sending. With an NVIDIA GPU, add the GPU override for several-times-faster generation (3–6 s per email on a laptop RTX 4050):

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

**No VPS? Host from your own PC.** A free [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connectivity/cloudflare-tunnel/) publishes the stack without a static IP or opening router ports, and Cloudflare provides HTTPS:

1. Add your domain to a free Cloudflare account, then create a tunnel under *Zero Trust → Networks → Tunnels* and copy its token.
2. In the tunnel, add a public hostname (e.g. `app.yourdomain.com`) pointing to service `http://web:80`.
3. In `.env`: `CLOUDFLARE_TUNNEL_TOKEN=<token>`, keep `SITE_ADDRESS=:80`, and set `PUBLIC_URL`, `BACKEND_BASE_URL`, `FRONTEND_BASE_URL`, `CSRF_TRUSTED_ORIGINS` to `https://app.yourdomain.com` and `ALLOWED_HOSTS=app.yourdomain.com,localhost,127.0.0.1`.
4. `docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile tunnel up -d`

The PC must stay on and awake. Turn on *Start Docker Desktop when you sign in*; the containers restart on their own.

To skip AI entirely (smaller server), set `AI_PROVIDER=none`; campaigns then send your templates with merge tags filled in.

Useful commands:

```sh
docker compose logs -f backend worker                       # follow logs
docker compose exec backend python manage.py createsuperuser # Django admin at /admin/
docker compose exec db pg_dump -U leadorbit leadorbit > backup.sql
git pull && docker compose up -d --build                    # update to the latest code
```

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
- `POST /api/v1/cron/tick/` (scheduler trigger for hosts without a Celery worker; needs `X-Cron-Secret`)
- `GET /api/v1/analytics/dashboard/`
- `POST /api/v1/webhooks/email/` (needs `WEBHOOK_SECRET` as `X-Webhook-Secret` or `?token=`)
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

- Some older root planning documents still mention the original `Lime` name, but the active README, backend, and frontend runtime paths use `LeadOrbit`.
- A `backend/.env.example` file exists but currently only documents `DEBUG` and `SECRET_KEY`. It is missing the Google 0Auth, Twilio, Celery and gemini variables that `backend/backend/settings.py` reads
- [`frontend/src`](frontend/src) and [`backend/config`](backend/config) look like leftover scaffold code and are not part of the main runtime path.
- Some endpoints are still MVP-grade and should be hardened before a production multi-tenant deployment; a few utility endpoints are intentionally permissive.
- The root markdown docs describe product intent and planning. The codebase is the source of truth for current behavior.

## Integration Notes

- Gmail sending requires valid Google OAuth client credentials and a connected account from the Settings page.
- SMS and call steps require Twilio credentials and leads with phone numbers.
- If no AI credentials are configured, the campaign builder AI composer still returns a deterministic fallback draft instead of failing hard.



## Contributors

Thanks to all contributors for their valuable efforts and support in making LeadOrbit better! ❤️

[![Contributors](https://contrib.rocks/image?repo=Kuldeeep18/LeadOrbit)](https://github.com/Kuldeeep18/LeadOrbit/graphs/contributors)
