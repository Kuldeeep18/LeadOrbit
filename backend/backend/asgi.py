import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
application = get_asgi_application()

from .startup import warn_missing_critical_settings

warn_missing_critical_settings()
