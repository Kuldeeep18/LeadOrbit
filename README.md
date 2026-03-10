# Lime (Lemlist-style Outreach MVP)

This repo contains:

- `backend/`: Django + DRF API, multi-tenant models, campaign execution tasks.
- `frontend/`: Static HTML/JS dashboard, leads, campaigns, analytics, settings.

## Quick Start

### 1) Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver 8000
```

Optional for background execution:

```powershell
# Terminal 2
cd backend
.\venv\Scripts\Activate.ps1
celery -A backend worker -l info

# Terminal 3
cd backend
.\venv\Scripts\Activate.ps1
celery -A backend beat -l info
```

### 2) Frontend

Serve `frontend/` as static files on `http://localhost:8080`:

```powershell
cd frontend
python -m http.server 8080
```

Open:

- `http://localhost:8080/login.html`

## Notes

- Backend base URL in frontend is `http://localhost:8000/api/v1`.
- Google OAuth callback expects `http://localhost:8000/api/v1/auth/google/callback`.
- Rotate secrets in `backend/.env` before sharing/deploying.
