# Development Phases

The project will be executed in 4 distinct phases to ensure rapid time-to-market while maintaining architectural integrity.

## Phase 1: Foundation (Weeks 1-2)
**Goal:** Establish the core data models, authentication, and multi-tenant environment.
- Setup Django + PostgreSQL + Celery Docker environment.
- Implement Custom User model and JWT Auth.
- Configure `TenantMiddleware` for organization isolation.
- Setup vanilla frontend tooling (Vite, Tailwind).
- Generate and wire up the basic Auth screens (Login, Register).

## Phase 2: Core Workflows (Weeks 3-4)
**Goal:** Enable users to manage data and build static sequences.
- Implement async CSV upload for Leads.
- Build the REST API for CRUD operations on Leads & Campaigns.
- Implement the visual Campaign Sequence Builder frontend.
- Establish the `CampaignLead` state machine.

## Phase 3: AI & Execution Engine (Weeks 5-6)
**Goal:** Turn the platform on. AI generation and actual email sending.
- Integrate Google Gemini API wrapper for personalization.
- Configure Celery Beat to query active `CampaignLeads`.
- Implement simple SMTP dispatch worker.
- Set up webhook consumption for Opens, Clicks, and Bounces.

## Phase 4: Real-time UI & Polish (Week 7)
**Goal:** Enhance the user experience with live data.
- Integrate Firebase Admin SDK for real-time dashboard notifications.
- Build out the Analytics dashboard API and charts.
- Perform end-to-end security and deliverability audits.
- Final deploy to staging/production.
