# LeadOrbit web: Caddy serves the static frontend, proxies the API and handles HTTPS.
FROM caddy:2.8-alpine

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY frontend/ /srv/frontend/

# Point the frontend at this site's own /api/v1 instead of localhost or the old host.
RUN printf "export const API_BASE_OVERRIDE = '/api/v1';\n" > /srv/frontend/runtime-config.js
