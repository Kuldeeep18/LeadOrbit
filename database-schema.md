# Database Schema
Primary datastore is PostgreSQL. All models inherit from a `TenantModel` that ensures an `organization_id` is required, isolating tenant data.

## Core Tables

### `Organization`
- `id`: UUID (PK)
- `name`: VARCHAR(255)
- `billing_plan`: VARCHAR(50)
- `created_at`: TIMESTAMP

### `User`
- `id`: UUID (PK)
- `organization_id`: UUID (FK)
- `email`: VARCHAR(255) (UNIQUE)
- `role`: ENUM('ADMIN', 'MANAGER', 'USER')
- `password_hash`: VARCHAR(255)

### `Lead`
- `id`: UUID (PK)
- `organization_id`: UUID (FK)
- `email`: VARCHAR(255)
- `first_name`: VARCHAR(100)
- `last_name`: VARCHAR(100)
- `phone`: VARCHAR(50)
- `linkedin_url`: VARCHAR(255)
- `custom_data`: JSONB (Indexed with GIN for fast querying)
- `global_unsubscribe`: BOOLEAN
- *Constraint: UNIQUE (organization_id, email)*

### `LeadTag`
- `id`: UUID (PK)
- `organization_id`: UUID (FK)
- `name`: VARCHAR(50)
- *(Has a Many-to-Many through table `Lead_LeadTag`)*

### `Campaign`
- `id`: UUID (PK)
- `organization_id`: UUID (FK)
- `name`: VARCHAR(255)
- `status`: ENUM('DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED')
- `settings`: JSONB (e.g., sending window schedule)

### `SequenceStep`
- `id`: UUID (PK)
- `campaign_id`: UUID (FK)
- `step_order`: INTEGER
- `channel_type`: ENUM('EMAIL', 'SMS', 'WHATSAPP', 'LINKEDIN', 'WAIT')
- `delay_minutes`: INTEGER (Delay from previous step to execute)
- `template_subject`: TEXT
- `template_body`: TEXT 

### `CampaignLead` (State Machine)
- `id`: UUID (PK)
- `campaign_id`: UUID (FK)
- `lead_id`: UUID (FK)
- `current_step_id`: UUID (FK, nullable)
- `status`: ENUM('ENROLLED', 'ACTIVE', 'PAUSED', 'REPLIED', 'BOUNCED', 'FINISHED')
- `next_execution_time`: TIMESTAMP (Indexed for rapid scheduler scans)
- *Constraint: UNIQUE (campaign_id, lead_id)*

### `Message`
- `id`: UUID (PK)
- `campaign_lead_id`: UUID (FK)
- `sequence_step_id`: UUID (FK)
- `channel`: ENUM('EMAIL', 'SMS', 'WHATSAPP', 'LINKEDIN')
- `generated_content`: TEXT (Stores the AI-generated final version)
- `status`: ENUM('PENDING', 'SENT', 'FAILED')
- `idempotency_key`: UUID (UNIQUE)
- `provider_message_id`: VARCHAR(255) (For webhooks)

### `MessageEvent` (Analytics)
- `id`: UUID (PK)
- `message_id`: UUID (FK)
- `event_type`: ENUM('DELIVERED', 'OPENED', 'CLICKED', 'REPLIED', 'BOUNCED')
- `timestamp`: TIMESTAMP
- `metadata`: JSONB
