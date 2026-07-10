<div align="center">

# 🛰️ LeadOrbit

**A multi-tenant outbound outreach platform** — CSV lead import, AI-assisted campaign building, Gmail/SMS/call sequencing, and engagement analytics.

![Python](https://img.shields.io/badge/Python-3.11.9-3776AB?style=flat-square&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-5-092E20?style=flat-square&logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-REST%20API-A30000?style=flat-square)
![Celery](https://img.shields.io/badge/Celery-Async%20Tasks-37814A?style=flat-square&logo=celery&logoColor=white)
![License](https://img.shields.io/badge/License-See%20Repo-lightgrey?style=flat-square)
![Tests](https://img.shields.io/badge/Backend%20Tests-27%20passing-brightgreen?style=flat-square)

> 📛 **Branding note:** the live app is **LeadOrbit**. Older planning docs in the repo root may still say *Lime* — ignore those, the code is the source of truth.

</div>

---

## 📑 Table of Contents

- [✨ What Works Today](#-what-works-today)
- [🧱 Stack](#-stack)
- [🗂️ Repo Layout](#️-repo-layout)
- [🔍 "I Want to Change X" — Quick Lookup](#-i-want-to-change-x--quick-lookup)
- [⚡ Local Setup](#-local-setup)
- [⏱️ Background Jobs](#️-background-jobs)
- [🖥️ Frontend Behavior](#️-frontend-behavior)
- [🔌 API Surface](#-api-surface)
- [✅ Testing](#-testing)
- [🛠️ Making Changes — Workflow](#️-making-changes--workflow)
- [⚠️ Current Caveats](#️-current-caveats)
- [🔗 Integration Notes](#-integration-notes)
- [🤝 Contributors](#-contributors)

---

## ✨ What Works Today

| Area | Status |
|---|---|
| JWT auth + organization creation on signup | ✅ |
| Tenant-scoped users, leads, campaigns, connected accounts | ✅ |
| CSV lead import (flexible column aliases, background task) | ✅ |
| Campaign builder (sequence editing, lead/sender selection, launch) | ✅ |
| Email sending via Gmail API | ✅ (needs connected Google account) |
| SMS / call execution via Twilio | ✅ (needs Twilio credentials) |
| Open / reply / click / bounce tracking via webhook | ✅ |
| AI draft generation (OpenRouter) with deterministic fallback | ✅ |
| Send-time personalization (Gemini merge tags) | ✅ (optional) |
| Dashboard & analytics pages | ✅ |
| Celery tasks: CSV import, campaign processing, reply polling | ✅ |

### Step-type execution status

```
✅ Fully implemented   EMAIL · SMS · CALL · WAIT · CONDITION_OPEN · CONDITION_REPLY · CONDITION_CLICK
🚧 Placeholder only     WHATSAPP · LINKEDIN · MANUAL   (visible in builder, auto-advance, no real send)
```

> 💡 **Good first issue:** wiring up real execution for `WHATSAPP`, `LINKEDIN`, or `MANUAL` steps.

---

## 🧱 Stack

<table>
<tr><td><b>Backend</b></td><td>Django 5 · Django REST Framework · Simple JWT · Celery · django-cors-headers</td></tr>
<tr><td><b>Frontend</b></td><td>Static HTML pages · ES modules · Bootstrap 5 · Chart.js (no build step)</td></tr>
<tr><td><b>Database</b></td><td>SQLite (<code>backend/db.sqlite3</code>) by default</td></tr>
<tr><td><b>Integrations</b></td><td>Google OAuth / Gmail API · OpenRouter · Gemini · Twilio</td></tr>
<tr><td><b>Python</b></td><td><code>3.11.9</code> (see <code>runtime.txt</code>)</td></tr>
</table>

---

## 🗂️ Repo Layout

```
backend/
├── manage.py
├── backend/          # ✅ active Django project (settings, urls, celery app)
├── campaigns/         # campaign models, serializers, tasks, Gmail/Twilio/AI integrations
├── leads/              # lead models, CSV import task, lead/tag API
├── tenants/            # organizations, tenant-scoping + security middleware
├── users/              # custom user model, registration, profile, JWT auth
└── config/            # ⚠️ leftover scaffold — not wired into manage.py

frontend/
├── *.html              # ✅ active screens (login, dashboard, leads, campaigns, builder, analytics, settings)
├── api.js              # API base URL + auth token helpers
├── main.js             # shared auth bootstrap / logout
├── theme.css           # shared dashboard styling
└── src/                # ⚠️ leftover Vite starter — not used by the live UI

outreach_frontend/       # currently empty — ignore
*.md                     # product/architecture planning docs (may be stale — code wins)
```

---

## 🔍 "I Want to Change X" — Quick Lookup

<details>
<summary><b>Click to expand the full map from feature → file</b></summary>

| I want to... | Go to |
|---|---|
| Change auth / JWT / signup logic | `backend/users/` |
| Change org / multi-tenant scoping | `backend/tenants/` (check middleware for tenant-leak bugs) |
| Change CSV import behavior or column aliases | `backend/leads/` (models + Celery task) |
| Add/modify a campaign step type | `backend/campaigns/` — models, serializers, step-execution tasks |
| Change Gmail sending logic | `backend/campaigns/` (Gmail integration) + Google OAuth config in `backend/backend/settings` |
| Change SMS/call sending | `backend/campaigns/` (Twilio integration) |
| Change AI draft generation / fallback | `backend/campaigns/` (OpenRouter/Gemini integration + fallback path) |
| Change webhook tracking (open/click/reply/bounce) | `backend/campaigns/` webhook view + `backend/backend/urls.py` |
| Change any UI screen | matching file in `frontend/*.html` — edit and reload, no build step |
| Change how the frontend finds the API | `frontend/api.js` |
| Change dashboard/analytics charts | `frontend/analytics.html` + `/api/v1/analytics/dashboard/` view |
| Change scheduled/background jobs | Celery tasks in `campaigns/` / `leads/`, Celery app config in `backend/backend/` |

</details>

---

## ⚡ Local Setup

<details open>
<summary><b>1. Virtual environment & dependencies</b></summary>

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```
</details>

<details>
<summary><b>2. Create <code>backend/.env</code></b></summary>

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
OPENROUTER_APP_NAME=LeadOrbit Campaign Builder

GEMINI_API_KEY=

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/v1/auth/google/callback

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
```

> 🔓 You don't need real Google/OpenRouter/Twilio keys to develop most features — AI falls back to a deterministic draft, SMS/calls just won't send, and Gmail sending is the only thing that hard-requires OAuth.
</details>

<details>
<summary><b>3. Migrate & run the backend</b></summary>

```bash
python backend/manage.py migrate

cd backend
python manage.py runserver 8000
```
</details>

<details>
<summary><b>4. Serve the frontend</b></summary>

```bash
cd frontend
python -m http.server 8080
```

Then open **`http://127.0.0.1:8080/login.html`** 🎉
</details>

---

## ⏱️ Background Jobs

By default (`CELERY_TASK_ALWAYS_EAGER=true` when `DEBUG=True`), CSV import and campaign processing run **synchronously** — no Redis required for everyday dev work.

To test real async execution:

```bash
# 1. Start Redis
# 2. Set CELERY_TASK_ALWAYS_EAGER=false in backend/.env
cd backend
celery -A backend worker -l info
celery -A backend beat -l info
```

> Reply polling only runs when `ENABLE_AUTO_REPLY_DETECTION=true`.

---

## 🖥️ Frontend Behavior

- The active frontend is the static `frontend/*.html` app — **no build step.**
- `frontend/api.js` defaults to `http://127.0.0.1:8000/api/v1` on localhost, and the deployed Render API elsewhere.
- Override the API base URL from the browser console:
  ```js
  localStorage.setItem('api_base_url', 'http://127.0.0.1:8000/api/v1');
  ```

**Main screens:** `login.html` · `register.html` · `dashboard.html` · `leads.html` · `campaigns.html` · `campaign-builder.html` · `analytics.html` · `settings.html`

---

## 🔌 API Surface

<details>
<summary><b>Click to expand endpoint list</b></summary>

```
POST   /api/v1/auth/register/
GET/PATCH /api/v1/auth/me/
POST   /api/v1/token/
POST   /api/v1/token/refresh/
GET/POST /api/v1/leads/
POST   /api/v1/leads/import_csv/
GET/POST/PATCH/DELETE /api/v1/campaigns/
POST   /api/v1/campaigns/{id}/enroll/
POST   /api/v1/campaigns/{id}/launch/
POST   /api/v1/campaigns/ai-generate/
GET    /api/v1/analytics/dashboard/
POST   /api/v1/webhooks/email/
GET    /api/v1/connected-accounts/
GET    /api/v1/auth/google/login
GET    /api/v1/auth/google/callback
```

> ✍️ Added a new endpoint? Update `api-contracts.md` in the same PR.
</details>

---

## ✅ Testing

```bash
cd backend
python manage.py test
```

**Current baseline: 27 passing tests**, covering:

- Auth / profile updates
- Lead import
- Tenant isolation
- Campaign creation & launch
- Non-email flow handling
- Conditional branching
- Connected-account ownership rules
- Reply polling
- AI fallback behavior

Add tests for new behavior in the relevant app's `tests` module before opening a PR.

---

## 🛠️ Making Changes — Workflow

```
1. Branch from main
   └─ e.g. feature/linkedin-step-execution, fix/analytics-tenant-scoping

2. Backend changes
   └─ Edit models → makemigrations → commit migration → update serializers/views
   └─ Verify Celery tasks still work with CELERY_TASK_ALWAYS_EAGER=true

3. Frontend changes
   └─ Edit the .html file directly, refresh browser (no build step)

4. Run tests
   └─ python manage.py test

5. Update docs
   └─ api-contracts.md / database-schema.md / this README, if user-facing

6. Open a PR against main
   └─ Clear description + linked issue
```

---

## ⚠️ Current Caveats

> These are known gaps, not surprises — good context before you dive into a related area.

- 🏷️ Some **root planning docs** still say *Lime* — active code/README use LeadOrbit.
- 🔑 The **Gemini API key field** in `settings.html` is **not persisted** — AI creds are read only from `backend/.env`.
- 🚫 The **danger-zone buttons** in `settings.html` are presentational only — nothing destructive is wired up.
- 🧹 `frontend/src/` and `backend/config/` are **leftover scaffolding** — not part of the live runtime.
- 🔓 **Analytics queries are currently unscoped** across tenants — a real gap worth fixing before production use.
- 🔓 A few utility endpoints are **intentionally permissive** for MVP speed — harden before wider deployment.
- 🚧 `WHATSAPP` / `LINKEDIN` / `MANUAL` steps are visible in the builder but **auto-advance without executing** anything real.

---

## 🔗 Integration Notes

| Integration | Requirement |
|---|---|
| **Gmail sending** | Valid Google OAuth client credentials + a connected account via Settings |
| **SMS / calls** | Twilio credentials + leads with phone numbers |
| **AI drafting** | Works with *no keys* — falls back to a deterministic draft instead of failing |

---

## 🤝 Contributors

Thanks to everyone helping make LeadOrbit better! ❤️

[![Contributors](https://contrib.rocks/image?repo=Kuldeeep18/LeadOrbit)](https://github.com/Kuldeeep18/LeadOrbit/graphs/contributors)

<!-- Add contributor avatars/links here, e.g. via https://contrib.rocks -->

---

<div align="center">

**Found something stale in this README?** Update it in the same PR as your code change — the docs should never drift further from reality than they already have. 🛰️

</div>
