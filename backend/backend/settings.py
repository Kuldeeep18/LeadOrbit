"""
Django settings for backend project.
"""
from pathlib import Path
import os
import re
import sys
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
TESTING = 'test' in sys.argv
# Prefer local project .env values for local development runs.
# Never override existing environment variables (important in deployment).
# Tests ignore .env so they behave the same on every machine and in CI.
if not TESTING:
    load_dotenv(BASE_DIR / '.env', override=False)


def _read_local_env_value(name: str, default: str = '') -> str:
    if TESTING:
        return default
    env_path = BASE_DIR / '.env'
    try:
        if env_path.exists():
            for raw_line in env_path.read_text(encoding='utf-8', errors='ignore').splitlines():
                line = raw_line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def _normalize_google_redirect_uri(raw_uri: str, backend_base_url: str) -> str:
    default_uri = f'{backend_base_url}/api/v1/auth/google/callback'
    candidate = (raw_uri or '').strip()
    if not candidate:
        return default_uri

    # Heal common typo: missing slash between host and path.
    candidate = re.sub(r'^(https?://[^/]+)(api/)', r'\1/\2', candidate, flags=re.IGNORECASE)

    if not (candidate.startswith('http://') or candidate.startswith('https://')):
        return default_uri

    scheme, rest = candidate.split('://', 1)
    host = rest.split('/', 1)[0].strip()
    if not host:
        return default_uri

    # Canonicalize callback path so Google/login/token-exchange always match.
    return f'{scheme}://{host}/api/v1/auth/google/callback'

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-change-me')
DEBUG = os.getenv('DEBUG', 'True').lower() in ('true', '1', 'yes')
MAILBOX_CREDENTIALS_ENCRYPTION_KEY = os.getenv(
    'MAILBOX_CREDENTIALS_ENCRYPTION_KEY',
    'fallback-insecure-key-for-local-dev-and-testing' if (DEBUG or TESTING) else '',
)
if not DEBUG and not TESTING and SECRET_KEY == 'django-insecure-fallback-key-change-me':
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('SECRET_KEY must be set when DEBUG is off.')

# Comma-separated, e.g. "leadorbit.example.com,localhost". Defaults to any host for local dev.
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]
# Needed for Django admin / unsubscribe form POSTs behind HTTPS, e.g. "https://leadorbit.example.com".
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]
# The reverse proxy (Caddy) terminates TLS and tells Django the original scheme.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_celery_beat',
    'tenants',
    'users',
    'leads',
    'campaigns',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # serves admin static files on PaaS hosts
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tenants.middleware.TenantMiddleware',  # custom tenant isolation
    'tenants.security.RateLimitMiddleware',  # API rate limiting
    'tenants.security.SecurityHeadersMiddleware',  # security headers
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Production (Docker) uses Postgres via DATABASE_URL=postgres://user:pass@host:5432/dbname
_database_url = os.getenv('DATABASE_URL', '').strip()
if _database_url:
    from urllib.parse import unquote, urlparse
    _db = urlparse(_database_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _db.path.lstrip('/'),
        'USER': unquote(_db.username or ''),
        'PASSWORD': unquote(_db.password or ''),
        'HOST': _db.hostname or '',
        'PORT': str(_db.port or 5432),
        'CONN_MAX_AGE': 60,
    }

AUTH_USER_MODEL = 'users.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
# `collectstatic` target (Django admin assets); served by the reverse proxy in Docker.
STATIC_ROOT = os.getenv('STATIC_ROOT', str(BASE_DIR / 'staticfiles'))
# Look files up per request in development instead of indexing STATIC_ROOT at startup.
WHITENOISE_AUTOREFRESH = DEBUG
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    )
}

# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
# In local/dev, execute tasks in-process so lead imports/campaign runs work without a worker.
CELERY_TASK_ALWAYS_EAGER = os.getenv(
    'CELERY_TASK_ALWAYS_EAGER',
    'true' if DEBUG else 'false',
).lower() in ('true', '1', 'yes')
CELERY_TASK_EAGER_PROPAGATES = True

CELERY_BEAT_SCHEDULE = {
    'process-campaign-leads-every-minute': {
        'task': 'campaigns.tasks.process_active_leads',
        'schedule': 60.0,
    },
    'check-imap-bounces-every-5-minutes': {
        'task': 'campaigns.tasks.check_imap_bounces',
        'schedule': 300.0,
    },
    'poll-gmail-replies-every-5-minutes': {
        'task': 'campaigns.tasks.poll_gmail_for_replies',
        'schedule': 300.0,
    },
}

# SimpleJWT Configuration
from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# Frontend origins allowed to call the API, e.g. "https://leadorbit.netlify.app".
# Unset (local dev) allows any origin.
_cors_origins = [o.strip() for o in os.getenv('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]
if _cors_origins:
    CORS_ALLOWED_ORIGINS = _cors_origins
    CORS_ALLOW_ALL_ORIGINS = False
else:
    CORS_ALLOW_ALL_ORIGINS = True

# AI personalization of outgoing emails: 'none' (default, sends templates as written),
# 'ollama' (self-hosted model) or 'gemini'. Tests always use 'none' (override_settings to test a provider).
AI_PROVIDER = 'none' if TESTING else os.getenv('AI_PROVIDER', _read_local_env_value('AI_PROVIDER', 'none'))
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', _read_local_env_value('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', _read_local_env_value('OLLAMA_MODEL', 'qwen2.5:3b'))
OLLAMA_TIMEOUT_SECONDS = int(os.getenv('OLLAMA_TIMEOUT_SECONDS', _read_local_env_value('OLLAMA_TIMEOUT_SECONDS', '60')))
# Keep the model in memory between sends so each email doesn't pay the load time.
OLLAMA_KEEP_ALIVE = os.getenv('OLLAMA_KEEP_ALIVE', _read_local_env_value('OLLAMA_KEEP_ALIVE', '30m'))

# Gemini API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', _read_local_env_value('GEMINI_API_KEY', ''))
GEMINI_MODEL = os.getenv('GEMINI_MODEL', _read_local_env_value('GEMINI_MODEL', 'gemini-3.8-flash'))

# Shared secret for POST /api/v1/cron/tick/ (runs the scheduler on hosts without
# a Celery worker). Empty disables the endpoint.
CRON_SECRET = os.getenv('CRON_SECRET', _read_local_env_value('CRON_SECRET', ''))
# A tick stops starting new sends after this many seconds so the request finishes
# well inside the gunicorn timeout; leftover leads go out on the next tick.
CRON_TICK_TIME_BUDGET_SECONDS = int(os.getenv('CRON_TICK_TIME_BUDGET_SECONDS', '60'))

# Shared secret for POST /api/v1/webhooks/email/ (open/click/reply/bounce events
# from an email provider). Send it as the X-Webhook-Secret header or ?token=.
# Empty disables the endpoint.
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', _read_local_env_value('WEBHOOK_SECRET', ''))

# Per-IP request limit for /api/ (per process). 0 disables it; tests disable it
# so suites don't trip over the shared in-memory counter.
API_RATE_LIMIT_PER_MINUTE = 0 if TESTING else int(os.getenv('API_RATE_LIMIT_PER_MINUTE', '100'))

# Reply detection toggle (used by Gmail polling task)
ENABLE_AUTO_REPLY_DETECTION = os.getenv(
    'ENABLE_AUTO_REPLY_DETECTION',
    'false',
).lower() in ('true', '1', 'yes')
ENABLE_AUTO_BOUNCE_DETECTION = os.getenv(
    'ENABLE_AUTO_BOUNCE_DETECTION',
    'true',
).lower() in ('true', '1', 'yes')

# Limit synchronous processing inside launch API calls to keep requests responsive.
LAUNCH_IMMEDIATE_PASSES = int(os.getenv('LAUNCH_IMMEDIATE_PASSES', '1' if DEBUG else '0'))

# Email backend (console for dev)
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# ─── Google OAuth2 / Gmail API ─────────────────────
BACKEND_BASE_URL = os.getenv(
    'BACKEND_BASE_URL',
    'http://localhost:8000' if DEBUG else 'https://leadorbit.onrender.com',
).rstrip('/')
FRONTEND_BASE_URL = os.getenv(
    'FRONTEND_BASE_URL',
    'http://localhost:8080' if DEBUG else '',
).rstrip('/')
# Served over HTTPS in production: keep the admin session and CSRF cookies off plain HTTP.
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG and BACKEND_BASE_URL.startswith('https://')
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = _normalize_google_redirect_uri(
    os.getenv('GOOGLE_REDIRECT_URI', ''),
    BACKEND_BASE_URL,
)
# In production, never allow localhost callback URLs. This avoids local .env leakage.
if not DEBUG and 'localhost' in GOOGLE_REDIRECT_URI.lower():
    GOOGLE_REDIRECT_URI = f'{BACKEND_BASE_URL}/api/v1/auth/google/callback'
GOOGLE_SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'openid',
]

