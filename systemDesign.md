# 🧠 System Design – Event Driven Outreach Engine

---

## 1. Core Execution Flow

1. Campaign created
2. Leads enrolled → CampaignLead entries
3. Celery scheduler queries:
   WHERE status='ACTIVE'
   AND next_execution_time <= now()
4. Worker processes step
5. AI content generated
6. Message dispatched
7. Event logged
8. State updated
9. Next step scheduled

---

## 2. Key Data Models

Organization
User
Lead
LeadTag
Campaign
SequenceStep
CampaignLead (state machine)
Message
MessageEvent
Unsubscribe
WebhookLog
AnalyticsSnapshot
AuditLog

---

## 3. Queue Separation

Queue Types:
- dispatch_queue
- webhook_queue
- import_queue
- ai_queue
- analytics_queue

Prevents bottlenecks.

---

## 4. AI Message Pipeline

build_prompt()
→ inject lead context
→ call Gemini
→ sanitize output
→ store generated content
→ dispatch

Add:
- Rate limiting
- Retry strategy
- Timeout fallback

---

## 5. Firebase Role

Used only for:
- Live dashboard updates
- Campaign status streaming
- Realtime notification system

Not used as primary database.

---

## 6. Reliability Mechanisms

- Idempotency key per Message
- Unique constraint on campaign_id + lead_id
- Soft deletes
- Retry with exponential backoff
- Dead letter queue

---

## 7. Deliverability Protection

- Throttling per sender
- Random dispatch jitter
- Bounce threshold auto-pause
- Domain verification checks
- Global suppression pre-dispatch validation

---

## 8. Scaling Strategy

Phase 1:
- Single server + workers

Phase 2:
- Dedicated worker machines
- Load balanced web nodes

Phase 3:
- Messaging microservice separation
- Event streaming architecture