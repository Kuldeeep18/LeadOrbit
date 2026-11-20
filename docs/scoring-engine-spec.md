# Lead Scoring Engine Specification

While the primary MVP focuses on delivery and AI generation, the analytics pipeline provides the foundation for an event-driven Lead Scoring Engine to prioritize hot leads for the sales team.

## 1. Goal
To automatically quantify lead engagement based on sequence interactions, surfacing the most interested prospects for manual intervention.

## 2. Event Point Allocation
Events processed from `webhook_queue` will synchronously increment or decrement a `score` integer on the `Lead` model.

**Positive Engagement:**
- **Email Opened**: +1 point (Max 3 points per campaign to prevent false positive pixel fires)
- **Link Clicked**: +5 points per unique link
- **Reply Received**: +15 points (Immediate state change to REPLIED overrides raw score importance)

**Negative Engagement:**
- **Soft Bounce**: -5 points (Retried by engine)
- **Hard Bounce**: -50 points (Lead marked invalid)
- **Unsubscribe**: -100 points (Added to global suppression list)

## 3. Implementation Mechanism
1. Provider webhook (e.g., SendGrid) hits Django endpoint.
2. Webhook payload is dumped to `webhook_queue`.
3. Celery worker parses the payload, identifies the `MessageEvent`.
4. Executes an atomic database transaction:
   ```sql
   UPDATE leads 
   SET score = score + :event_value 
   WHERE id = :lead_id;
   ```
5. If `score` crosses a defined threshold (e.g., > 10), trigger a Firebase real-time notification to the assigned User's dashboard.
