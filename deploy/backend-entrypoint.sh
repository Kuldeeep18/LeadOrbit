#!/bin/sh
# Starts one LeadOrbit backend role: web (API), worker (Celery) or beat (scheduler).
set -e

case "$1" in
  web)
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput
    exec gunicorn backend.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout "${GUNICORN_TIMEOUT:-120}" \
      --access-logfile -
    ;;
  worker)
    exec celery -A backend worker --loglevel=INFO --concurrency="${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A backend beat --loglevel=INFO --schedule /tmp/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
