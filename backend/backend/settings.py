"""
Django settings for backend project.
"""
from pathlib import Path
import os
import re
import sys
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Prefer local project .env values for local development runs.
# Never override existing environment variables (important in deployment).
load_dotenv(BASE_DIR / '.env', override=False)


def _read_local_env_value(name: str, default: str = '') -> str:
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

# ─── CRITICAL SECURITY FIX: SECRET_KEY must be set in environment ───
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable is not set. Please set it in your .env file or environment.")

# ─── CRITICAL SECURITY FIX: DEBUG defaults to False (fail-safe) ───
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 'yes')
TESTING = 'test' in sys.argv

# ─── CRITICAL SECURITY FIX: Encryption key must be set in production ───
MAILBOX_CREDENTIALS_ENCRYPTION_KEY = os.getenv('MAILBOX_CREDENTIALS_ENCRYPTION_KEY')
if not MAILBOX_CREDENTIALS_ENCRYPTION_KEY and not DEBUG and not TESTING:
    raise ValueError(
        "MAILBOX_CREDENTIALS_ENCRYPTION_KEY environment variable is not set. "
        "Please set it in your .env file or environment."
    )
# Allow fallback only for development/testing
if not MAILBOX_CREDENTIALS_ENCRYPTION_KEY:
    MAILBOX_CREDENTIALS_ENCRYPTION_KEY = 'fallback-insecure-key-for-local-dev-and-testing'

# ─── FIX: ALLOWED_HOSTS from environment, not wildcard ───
ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

# ─── CRITICAL SECURITY FIX: CORS Configuration ──────────────────────────
# Use explicit whitelist instead of allowing all origins
CORS_ALLOW_ALL_ORIGINS = False

# Define explicit allowed origins
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:3000,http://127.0.0.1:3000'
).split(',')

# Remove empty strings and strip whitespace
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in CORS_ALLOWED_ORIGINS if origin.strip()]

# For production, you can add:
# CORS_ALLOWED_ORIGINS = [
#     "https://leadorbit.com",
#     "https://www.leadorbit.com",
# ]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',  # ADDED - Fix #606
    'corsheaders',
    'django_celery_beat',
    'tenants',
    'users',
    'leads',
    'campaigns',
    'csp',  # ADDED - Fix #624
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'csp.middleware.CSPMiddleware',  # ADDED - Fix #624
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

AUTH_USER_MODEL = 'users.User'

# ─── CRITICAL SECURITY FIX: Password Policy ──────────────────────────
# Increased minimum length from default 8 to 12 (Fix #622)
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 12,  # ✅ Increased from default 8
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
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

# ─── CRITICAL SECURITY FIX: SimpleJWT Configuration ────────────────────
# Explicitly set algorithm and signing key (Fix #618)
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    
    # ─── CRITICAL SECURITY FIX: Explicit JWT algorithm ──────────────
    # Explicitly set algorithm to HS256 (or RS256 for production)
    'ALGORITHM': 'HS256',  # Fix #618
    
    # ─── FIX: Fallback to SECRET_KEY if JWT_SIGNING_KEY not set ───
    'SIGNING_KEY': os.getenv('JWT_SIGNING_KEY') or SECRET_KEY,
    
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    # Additional security settings
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'JTI_CLAIM': 'jti',
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# ─── Session & CSRF Cookie Security ──────────────────────────────
# Ensure cookies are only sent over HTTPS in production
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# Prevent client-side JavaScript access to session cookie
SESSION_COOKIE_HTTPONLY = True

# Restrict cookie to same-origin requests
SESSION_COOKIE_SAMESITE = 'Lax'

# CSRF cookie settings
CSRF_COOKIE_HTTPONLY = False  # Required for JavaScript to read token
CSRF_COOKIE_SAMESITE = 'Lax'

# Optional: Set cookie age
SESSION_COOKIE_AGE = 86400  # 24 hours

# ─── CRITICAL SECURITY FIX: Content Security Policy (CSP) ──────────────
# Added to prevent XSS attacks (Fix #624)
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = ("'self'",)
CSP_STYLE_SRC = ("'self'",)
CSP_IMG_SRC = ("'self'", "data:",)
CSP_FONT_SRC = ("'self'",)
CSP_CONNECT_SRC = ("'self'",)
CSP_OBJECT_SRC = ("'none'",)
CSP_BASE_URI = ("'none'",)
CSP_FRAME_ANCESTORS = ("'none'",)
CSP_FORM_ACTION = ("'self'",)
CSP_REPORT_URI = "/csp-report/"

# For development with inline styles/scripts
if DEBUG:
    CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'", "'unsafe-eval'")
    CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")

# Gemini API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', _read_local_env_value('GEMINI_API_KEY', ''))
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', _read_local_env_value('OPENROUTER_API_KEY', ''))
OPENROUTER_MODEL = os.getenv('OPENROUTER_MODEL', _read_local_env_value('OPENROUTER_MODEL', 'mistralai/mistral-nemo'))
OPENROUTER_APP_URL = os.getenv('OPENROUTER_APP_URL', _read_local_env_value('OPENROUTER_APP_URL', 'http://localhost:8080'))
OPENROUTER_APP_NAME = os.getenv('OPENROUTER_APP_NAME', _read_local_env_value('OPENROUTER_APP_NAME', 'LeadOrbit Campaign Builder'))

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

# ─── Twilio SMS & Voice ─────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', _read_local_env_value('TWILIO_ACCOUNT_SID', ''))
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', _read_local_env_value('TWILIO_AUTH_TOKEN', ''))
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', _read_local_env_value('TWILIO_PHONE_NUMBER', ''))

# ─── FIX: Cache Configuration (for rate limiting) ────────
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': os.getenv('REDIS_URL', 'redis://localhost:6379/1'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            # ─── FIX: Use CONNECTION_POOL_KWARGS instead of deprecated options ───
            'CONNECTION_POOL_KWARGS': {
                'max_connections': 50,
                'timeout': 20,
            },
            'PICKLE_VERSION': -1,
        },
    }
}

