# API Contracts
The platform uses semantic REST principles built via Django REST Framework. Authentication is managed via JWT.

## General Principles
- **Base Path**: `/api/v1/`
- **Auth**: `Header: Authorization: Bearer <token>`
- **Response Structure (Success)**: 200/201 HTTP Status Code, raw JSON object or array.
- **Response Structure (Error)**: 4xx/5xx HTTP Status Code, `{"detail": "Error message explanation"}`

## Endpoints

### 1. Authentication
**`POST /api/v1/auth/login/`**
- **Req**: `{"email": "user@co.com", "password": "xyz"}`
- **Res**: `{"access_token": "jwt...", "refresh_token": "jwt..."}`

**`POST /api/v1/auth/register/`**
- **Req**: `{"email": "...", "password": "...", "organization_name": "..."}`
- **Res**: `{"access_token": "...", "organization_id": "..."}`

### 2. Leads
**`GET /api/v1/leads/`**
- **Query Params**: `?page=1&page_size=50&status=active&search=smith`
- **Res**: `{"count": 12, "next": null, "previous": null, "results": [...]}`

**`POST /api/v1/leads/`**
- **Req**: `{"email": "...", "first_name": "...", "custom_data": {"role": "CEO"}}`
- **Res**: Lead Object

**`POST /api/v1/leads/import/`**
- **Req**: `multipart/form-data` with `file` (CSV), plus JSON configuration mapping CSV columns to Lead fields.
- **Res**: `{"task_id": "uuid", "message": "Import queued successfully"}`

### 3. Campaigns
**`GET /api/v1/campaigns/`**
- **Res**: List of Campaigns with aggregated active counts (paginated).

**`POST /api/v1/campaigns/`**
- **Req**: `{"name": "Q3 Outreach", "settings": {"schedule": "..."}}`
- **Res**: Campaign Object

**`POST /api/v1/campaigns/{id}/enroll/`**
- **Req**: `{"lead_ids": ["uuid", "uuid"], "tag_ids": ["uuid"]}`
- **Res**: `{"enrolled_count": 50}`

### 4. Sequences
**`POST /api/v1/campaigns/{id}/steps/`**
- **Req**: `{"step_order": 1, "channel_type": "EMAIL", "delay_minutes": 0, "template_subject": "Hello {{first_name}}", "template_body": "..."}`
- **Res**: SequenceStep Object

### 5. Analytics
**`GET /api/v1/campaigns/{id}/analytics/`**
- **Res**: 
```json
{
  "total_enrolled": 500,
  "metrics": {
    "sent": 450,
    "opened": 200,
    "clicked": 50,
    "replied": 25,
    "bounced": 5
  },
  "rates": {
    "open_rate": 0.44,
    "reply_rate": 0.05
  }
}
```
