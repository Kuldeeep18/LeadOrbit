# User Stories & Acceptance Criteria

## 1. Authentication & Organization Management
**User Story:** As an Admin, I want to create an organization workspace so that my team can collaborate securely.
- **Acceptance Criteria:**
  - Users can sign up and implicitly create an organization.
  - Admins can invite team members via email.
  - Data is isolated by `organization_id`.

## 2. Lead Management
**User Story:** As a User, I want to upload a CSV of leads so I can add them to outreach campaigns.
- **Acceptance Criteria:**
  - CSV files up to 10k rows process seamlessly in the background.
  - Users can map CSV columns to standard attributes (Name, Email, Phone) and custom JSON attributes.
  - Duplicate emails within the same organization are merged or skipped based on user preference.

**User Story:** As a User, I want to tag leads so I can segment them for specialized campaigns.
- **Acceptance Criteria:**
  - Leads can have multiple tags.
  - Users can filter the lead table by tags.

## 3. Campaign Building
**User Story:** As a User, I want to create a multi-step campaign across various channels.
- **Acceptance Criteria:**
  - Interface provides a visual builder to add steps (Email, SMS, LinkedIn, Wait).
  - Users can define specific delays between steps (e.g., wait 3 days).
  - Users can set a campaign-wide sending window (e.g., 9-5 PM EST, Mon-Fri).

**User Story:** As a User, I want to inject AI-generated personalization into my message templates.
- **Acceptance Criteria:**
  - Template editor supports standard variables (`{{first_name}}`) and AI prompts (`[[Generate custom icebreaker based on {{industry}}]]`).
  - System preview shows what the AI step evaluates to for a sample lead.

## 4. Campaign Execution & Safety
**User Story:** As a User, I want my sequence to automatically stop if a lead replies.
- **Acceptance Criteria:**
  - System ingests incoming replies.
  - CampaignLead state transitions to "Replied".
  - Subsequent scheduled sequence steps are canceled.

**User Story:** As a Developer/System, I want to protect deliverability by ensuring messages aren't sent too quickly.
- **Acceptance Criteria:**
  - System applies random dispatch jitter to simulated human sends.
  - Accounts have daily send limits that cannot be exceeded.
  - High bounce rates automatically pause the campaign.

## 5. Analytics
**User Story:** As a User, I want to see my campaign metrics at a glance to gauge performance.
- **Acceptance Criteria:**
  - Dashboard shows Sent, Opened, Clicked, and Reply rates.
  - Users can see metrics broken down by individual sequence steps.
