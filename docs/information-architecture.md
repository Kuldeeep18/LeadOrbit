# Information Architecture

## Sitemap & Navigation Structure

### 1. Public / Unauthenticated
- **`/login`**: User authentication via Email/Password or SSO.
- **`/register`**: Organization and Admin onboarding.
- **`/forgot-password`**: Password recovery flow.

### 2. Global Application Layout
- **Sidebar Navigation** (Persistent):
  - Dashboard (Home)
  - Leads
  - Campaigns
  - Mailboxes / Integrations
  - Analytics
  - Settings
- **Top Bar**: Search (Global Lead/Campaign search), Tenant Switcher (if applicable), User Profile/Logout, Notifications (Firebase real-time).

### 3. Route Hierarchy

#### `/dashboard` (Home)
- **High-level Metrics**: Aggregate stats (Total Leads, Active Campaigns, Reply Rates).
- **Recent Activity**: Stream of system events (Responses, bounces, completions).

#### `/leads`
- **Lead List View**: Data table, pagination, search, filter by tag/status, bulk actions.
- **Lead Detail View (`/leads/:id`)**: Overview of contact info, historical activity feed, active campaigns, custom attributes.
- **Import Wizard**: Step-by-step CSV upload and column mapping.

#### `/campaigns`
- **Campaign List View**: Card or table view of drafts, active, and paused campaigns with top-line stats.
- **Campaign Builder (`/campaigns/new` or `/campaigns/:id/edit`)**: Multi-step visual sequence builder, scheduling windows, lead enrollment.
- **Campaign Overview (`/campaigns/:id`)**: Detailed performance analytics, sequence diagram, enrolled lead states.

#### `/mailboxes`
- **Connection Hub**: List of connected email providers, SMS numbers, and LinkedIn accounts.
- **Oauth Flows**: Connect new Google / Microsoft accounts.
- **Health Dashboard**: Warmup status, daily volume limits, and disconnect alerts.

#### `/analytics`
- **Global Reports**: Comprehensive charts (e.g., line charts for daily sends vs replies).
- **Deliverability Hub**: Bounce rates, spam complaints, and infrastructure health.

#### `/settings`
- **Profile**: Personal information and password changes.
- **Organization**: Company details, global unsubscribe lists, billing.
- **Team**: Invite users, manage RBAC permissions.
