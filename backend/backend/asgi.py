import os
from django.core.asgi import get_asgi_application
from .startup import warn_missing_startup_env_vars

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
application = get_asgi_application()
warn_missing_startup_env_vars()
