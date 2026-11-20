# Engineering Scope

This document defines the strict engineering scope for the Minimum Viable Product (MVP) build of Lime.

## 1. In Scope (MVP)

**Authentication & Security:**
- JWT-based authentication.
- Multi-tenant data segregation at the database query layer.

**Core Data Pipelines:**
- Async CSV ingestion handling up to 10,000 rows per file without timing out.
- Dynamic custom JSON variable mapping.

**Campaign Engine:**
- Visual sequence builder supporting EMAIL and WAIT steps *only* for MVP.
- Stop-on-reply logic based on inbound email parsing or provider webhooks.
- Scheduled dispatching via Celery Beat cron jobs.

**AI Integration:**
- Integration with Google Gemini API (Free Tier for MVP testing).
- Prompt template parsing injecting lead variables before sending to Gemini.

**Frontend UI:**
- Migration from React to Vanilla JS/Alpine.js utilizing Stitch MCP generated Tailwind templates.
- Dashboard, Leads Management, Campaign Builder, and Mailbox Integration views.

## 2. Out of Scope (Deferred to Phase 2+)

**Features Excluded from MVP:**
- **Advanced Channels**: SMS, WhatsApp, and LinkedIn automation are deferred.
- **Complex AI Analysis**: Intent classification on replies (e.g., figuring out if a human replied "Yes" vs "Not interested"). MVP will just stop the sequence on *any* reply.
- **Warm-up Network**: Automated sending between customer inboxes to build sender reputation.
- **A/B Testing**: Multivariate testing of subject lines and body copy.
- **Provider OAuth**: Implementing strict Google/Microsoft OAuth flows for mailboxes; MVP will rely on SMTP / App Passwords or a simple API Relay provider.
