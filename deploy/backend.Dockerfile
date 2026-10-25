# LeadOrbit backend: Django API (gunicorn), Celery worker and Celery beat share this image.
FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY backend/ /app/
COPY deploy/backend-entrypoint.sh /usr/local/bin/leadorbit-entrypoint

# Run as an unprivileged user; staticfiles is shared with the web container.
RUN sed -i 's/\r$//' /usr/local/bin/leadorbit-entrypoint \
    && chmod +x /usr/local/bin/leadorbit-entrypoint \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/staticfiles \
    && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["leadorbit-entrypoint"]
CMD ["web"]
