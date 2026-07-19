# 🏗 Architecture – AI Multi-Channel Outreach Platform

## 1. Architectural Philosophy

The system is designed as:

- Multi-tenant SaaS
- Event-driven automation engine
- Async-first processing
- AI-native personalization layer
- Horizontally scalable

---

## 2. High-Level Architecture

Frontend (Stitch MCP HTML/CSS/JS)
        ↓
Django API Layer (Business Logic + Multi-Tenancy)
        ↓
PostgreSQL (Primary Structured Data)
        ↓
Firebase
   - Realtime notifications
   - Live campaign dashboards
   - Websocket-like UI sync
        ↓
Task Queue (Celery Workers)
        ↓
Messaging Providers
   - Email
   - SMS
   - WhatsApp
   - LinkedIn Automation Layer
        ↓
Gemini AI Service (Content Engine)

---

## 3. Core Architectural Layers

### A. Presentation Layer
- Stitch MCP generates HTML templates.
- Tailwind-based UI.
- AJAX/Fetch for API communication.
- Firebase used for live dashboard updates.

### B. Application Layer (Django Apps)

apps/
│
├── tenants/
├── users/
├── leads/
├── campaigns/
├── sequences/
├── dispatch/
├── ai_engine/
├── analytics/
├── compliance/
└── monitoring/

---

### C. Automation Engine

- CampaignLead acts as state machine.
- Celery schedules next_execution_time.
- Workers execute steps.
- Conditional branching handled server-side.

---

### D. AI Layer

AI abstraction layer:

- generate_email()
- generate_sms()
- generate_linkedin_message()
- generate_subject_line()
- analyze_reply_intent()

All prompts routed via Gemini wrapper service.

Provider-agnostic design.

---

## 4. Multi-Tenant Isolation

- Shared database
- Strict organization_id on root tables
- Custom TenantMiddleware
- Automatic ORM filtering
- Hard database-level unique constraints per tenant

---

## 5. Scalability Principles

- Stateless Django web nodes
- Separate worker pool
- Read-optimized analytics snapshots
- GIN indexes on JSONB fields
- Queue partitioning by job type