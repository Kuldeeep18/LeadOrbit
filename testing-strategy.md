# Testing Strategy

Given the automated, high-volume nature of the outreach platform, rigorous testing is critical to prevent catastrophic failures like sending the wrong email to a lead or sending duplicate emails.

## 1. Unit Testing (Backend)
**Tool**: `pytest` + `pytest-django`
- **Scope**: Testing isolated business logic, model methods, and serializers.
- **Crucial Areas**: 
  - `TenantMiddleware` (Ensure User A can NEVER query Lead B).
  - State machine transitions (Ensure a lead goes from 'ENROLLED' to 'ACTIVE' correctly).
  - Validation logic preventing campaigns from scheduling steps in the past.

## 2. Integration Testing
- **Scope**: Testing the interaction between Django, the database, and Celery.
- **Crucial Areas**:
  - Validating that bulk CSV processing successfully maps data and inserts records without duplicating.
  - Testing the Celery execution pipeline: Mocking the Gemini API and testing that a dispatched task correctly processes the mock data, updates the `CampaignLead` state, and schedules the *next* task.

## 3. End-to-End (E2E) Testing
**Tool**: Playwright or Cypress
- **Scope**: User flows across the UI.
- **Crucial Areas**:
  - The entire Campaign creation wizard.
  - Ensuring the visual sequence builder accurately maps to JSON payloads sent to the backend.
  - Login and Registration flows.

## 4. Manual QA & Deliverability Testing
- Testing HTML rendering of dispatched emails across major clients (Gmail, Outlook, Apple Mail).
- Verifying bounce handling logic by sending tests to known bad addresses and validating the system halts the sequence for that lead. 
