from django.conf import settings

_WARNED = False


def warn_missing_startup_env_vars():
    global _WARNED
    if _WARNED:
        return

    required = ('GEMINI_API_KEY', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET')
    missing = [name for name in required if not str(getattr(settings, name, '') or '').strip()]
    if not missing:
        return

    _WARNED = True
    print(
        f"\033[1m[LeadOrbit startup warning]\033[0m Missing environment variables: {', '.join(missing)}",
        flush=True,
    )
