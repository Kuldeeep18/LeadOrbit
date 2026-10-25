// Deployment-time settings. The Docker image overwrites this file so the app
// calls the API on its own origin ('/api/v1'). Leave empty for local dev:
// api.js then uses http://127.0.0.1:8000 on localhost, or the hosted backend.
export const API_BASE_OVERRIDE = '';
