"""Startup checks for critical deployment settings."""

import sys

from django.conf import settings

CRITICAL_STARTUP_SETTINGS = (
    'GEMINI_API_KEY',
    'GOOGLE_CLIENT_ID',
    'GOOGLE_CLIENT_SECRET',
)


def warn_missing_critical_settings(stream=None):
    """
    Print a bold-style warning for missing startup settings and return them.
    """
    missing = [
        name
        for name in CRITICAL_STARTUP_SETTINGS
        if not str(getattr(settings, name, '') or '').strip()
    ]

    if not missing:
        return []

    output = stream or sys.stdout
    print(
        '*** WARNING: Missing LeadOrbit startup settings: '
        f"{', '.join(missing)} ***",
        file=output,
        flush=True,
    )
    return missing
