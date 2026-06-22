import os
from django.core.wsgi import get_wsgi_application
from .startup import warn_missing_startup_env_vars

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
application = get_wsgi_application()
warn_missing_startup_env_vars()
