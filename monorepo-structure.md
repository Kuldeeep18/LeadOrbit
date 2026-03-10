# Monorepo Structure

To maintain rapid development and ease of cross-layer debugging, Lime will utilize a monorepo structure separating the Stitch MCP generated frontend from the Django backend ecosystem.

```text
/lime-monorepo
│
├── /frontend                        # Stitch MCP generated HTML/JS/CSS target
│   ├── /public                      # Static assets (images, fonts)
│   ├── /src
│   │   ├── /css                     # Tailwind compiled CSS & base styles
│   │   ├── /js
│   │   │   ├── api.js               # Global Axios/Fetch wrappers
│   │   │   ├── auth.js              # Token management
│   │   │   └── utils.js             # Formatting, helpers
│   │   └── /pages                   # Compiled HTML files from MCP
│   ├── package.json                 # Tooling (Vite, Tailwind CLI)
│   └── vite.config.js               # Frontend Dev Server configuration
│
├── /backend                         # Django Application
│   ├── /config                      # Project settings (settings.py, urls.py, wsgi, asgi)
│   ├── /apps                        # Isolated Django Apps
│   │   ├── /tenants                 # Org logic, middleware
│   │   ├── /users                   # Custom User model, auth strategies
│   │   ├── /leads                   # Lead ingestion, parsing, querying
│   │   ├── /campaigns               # Core business logic for state machines
│   │   ├── /sequences               # Step models, rule definitions
│   │   ├── /dispatch                # Webhooks, Celery task distributors
│   │   ├── /ai_engine               # Gemini prompt wrappers and logic
│   │   ├── /analytics               # Event tracking, reporting aggregations
│   │   └── /monitoring              # Health checks, dead-letter logic
│   ├── manage.py
│   └── requirements.txt
│
├── /worker                          # Background Processing Configs
│   ├── celery_app.py                # Main Celery app instance logic
│   └── tasks/                       # Core recurring task definitions
│
├── /microservices
│   └── /linkedin-automation         # Future Node.js/Puppeteer or API gateway for LinkedIn
│
├── /infra                           # DevOps & Deployment Definitions
│   ├── docker-compose.yml           # Local dev orchestrator (Postgres, Redis, Web, Worker)
│   ├── /terraform                   # Cloud infrastructure as code
│   └── /k8s                         # Production manifests
│
└── .gitignore
```
