# Environment and DevOps Strategy

## 1. Hosting Architecture
Lime will utilize a containerized deployment strategy for consistency across environments.

- **Web Tier**: Stateless Django instances running via Gunicorn, deployed on an auto-scaling Platform as a Service (e.g., Render, Heroku) or AWS ECS.
- **Worker Tier**: Persistent Celery worker compute nodes, scaled dynamically based on queue length.
- **Data Tier**: 
  - Managed PostgreSQL instance (e.g., Amazon RDS or Supabase) for primary data.
  - Managed Redis (e.g., ElastiCache) for Celery task brokering and simple caching.

## 2. Environments

- **Local (Dev)**: Entire stack runs via a single `docker-compose up` command, spinning up Postgres, Redis, Django, and Vite.
- **Staging**: A mirror of production with sanitized data. Used by QA and stakeholders to sign off on features before release.
- **Production**: High-availability, multi-AZ deployment with strict network isolation.

## 3. Continuous Integration & Delivery (CI/CD)

**Tool:** GitHub Actions

### Workflow Steps on PR to `main`:
1. **Linting**: Run `flake8` and `black` on backend code.
2. **Unit Tests**: Spin up ephemeral Postgres via GitHub Actions services, run `pytest`.
3. **Build**: Build frontend static assets via Vite.

### Workflow Steps on Merge to `main`:
1. Run CI suite again to ensure merge stability.
2. Build Docker images for production.
3. Push images to Container Registry.
4. Trigger rolling restart on Web and Worker tiers via deployment webhooks.
5. Automatically run Django migrations.
