# FDC Tax Core + CRM Sync API

Backend API for FDC Tax CRM sync, user onboarding state, Meet Oscar wizard integration, and recurring task automation.

## Overview

This API connects the MyFDC frontend to the internal CRM system, providing:
- User profile and onboarding state management
- Meet Oscar wizard integration
- Task management and CRM sync
- **Recurring Task Engine** - Automatic task generation based on iCal RRULE
- Knowledge base access for Luna AI
- White-glove service layer for FDC Tax team

## Database

The API connects to the FDC Tax PostgreSQL sandbox database with the following schemas:
- `myfdc` - Main application tables (users, user_tasks, user_settings, luna_knowledge_base)
- `crm` - Internal CRM tables (tasks, messages)

## Quick Start

```bash
# Backend
cd /app/backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# API Documentation
open http://localhost:8001/docs
```

---

## Recurring Task Engine

The recurring task engine automatically generates tasks based on iCal RRULE recurrence rules. This is used for BAS reminders, income prompts, and other scheduled compliance tasks.

### RRULE Format

The engine uses standard iCal RRULE format. Common examples:

| Pattern | RRULE | Description |
|---------|-------|-------------|
| Monthly on 28th | `FREQ=MONTHLY;BYMONTHDAY=28` | Monthly BAS reminder |
| Quarterly BAS | `FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=28` | Jan, Apr, Jul, Oct |
| Weekly Friday | `FREQ=WEEKLY;BYDAY=FR` | Weekly income check |
| Last day of month | `FREQ=MONTHLY;BYMONTHDAY=-1` | End of month review |
| Yearly June 30 | `FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=30` | EOFY preparation |
| Every 2 weeks | `FREQ=WEEKLY;INTERVAL=2` | Bi-weekly |
| Mon, Wed, Fri | `FREQ=WEEKLY;BYDAY=MO,WE,FR` | Multiple days |

### API Endpoints

#### Template Management (`/api/recurring`)

```bash
# List all recurring templates
GET /api/recurring/templates
GET /api/recurring/templates?user_id=<uuid>&active_only=true

# Get specific template
GET /api/recurring/templates/{template_id}

# Create new template
POST /api/recurring/templates
Content-Type: application/json
{
  "user_id": "uuid",
  "title": "Monthly BAS Check",
  "description": "Review BAS before submission",
  "priority": "high",
  "category": "compliance",
  "recurrence_rule": "FREQ=MONTHLY;BYMONTHDAY=21"
}

# Update template
PATCH /api/recurring/templates/{template_id}
{
  "title": "Updated Title",
  "is_active": false
}

# Delete template
DELETE /api/recurring/templates/{template_id}
```

#### Predefined Templates

```bash
# List available predefined templates
GET /api/recurring/predefined

# Apply predefined template to user
POST /api/recurring/predefined/{template_key}?user_id=<uuid>
```

Available predefined templates:
- `monthly_bas_reminder` - Monthly on the 21st
- `quarterly_bas_submission` - Quarterly on the 28th (Jan, Apr, Jul, Oct)
- `weekly_income_check` - Weekly on Friday
- `monthly_expense_review` - Monthly on the last day
- `eofy_preparation` - Yearly on June 1st
- `tax_return_reminder` - Yearly on October 1st

#### Task Generation

```bash
# Trigger recurring task generation (admin endpoint)
POST /api/admin/tasks/trigger-recurring
POST /api/admin/tasks/trigger-recurring?user_id=<uuid>
POST /api/admin/tasks/trigger-recurring?force=true

# Alternative path
POST /api/recurring/trigger?user_id=<uuid>&force=true
```

In production, the trigger endpoint should be called by a daily cron job:
```bash
# Example cron entry (run daily at 6 AM)
0 6 * * * curl -X POST https://api.fdctax.com/api/admin/tasks/trigger-recurring
```

#### Utilities

```bash
# Preview next occurrences for a rule
POST /api/recurring/preview?rule=FREQ%3DMONTHLY%3BBYMONTHDAY%3D28&count=5

# Get human-readable summary
GET /api/recurring/summary?rule=FREQ%3DWEEKLY%3BBYDAY%3DMO%2CFR
# Returns: {"summary": "Weekly on Monday, Friday", "next_occurrence": "2025-12-29"}
```

### Example Payloads

#### Create Quarterly BAS Reminder
```json
{
  "user_id": "1185602f-d78e-4a55-92c4-8a87d5f9714e",
  "title": "Quarterly BAS Due",
  "description": "Your quarterly BAS is due in 7 days. Please review all income and expenses.",
  "priority": "high",
  "category": "compliance",
  "recurrence_rule": "FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=21",
  "recurrence_summary": "Quarterly on the 21st"
}
```

#### Create Weekly Check-in
```json
{
  "user_id": "1185602f-d78e-4a55-92c4-8a87d5f9714e",
  "title": "Weekly Receipt Upload",
  "description": "Upload any receipts from this week",
  "priority": "normal",
  "category": "expenses",
  "recurrence_rule": "FREQ=WEEKLY;BYDAY=SU"
}
```

### Generated Task Format

When a recurring task is generated, it appears in `myfdc.user_tasks` with:
- `task_type`: "recurring"
- `due_date`: Calculated from RRULE
- `description`: Original description + "[Auto-generated from recurring template: {summary}]"

---

## API Endpoints Summary

### Health Check
```
GET /api/           - Basic health check
GET /api/health     - Detailed health with database status
```

### User Endpoints (`/api/user`)
```
GET  /api/user/tasks?user_id=<uuid>           - Get tasks for logged-in user
GET  /api/user/profile?user_id=<uuid>         - Get user profile + setup state
POST /api/user/profile?user_id=<uuid>         - Update user profile
POST /api/user/oscar?user_id=<uuid>           - Toggle Oscar preprocessing
PATCH /api/user/onboarding?user_id=<uuid>     - Update setup_state flags
GET  /api/user/onboarding/status?user_id=<uuid> - Get current onboarding status
```

### Admin / White-Glove Endpoints (`/api/admin`)
```
GET  /api/admin/users                         - List all users (with filters)
GET  /api/admin/users/{user_id}               - Get specific user
GET  /api/admin/users/email/{email}           - Get user by email
PATCH /api/admin/users/{user_id}              - Update user details

GET  /api/admin/profiles/{user_id}            - Get user profile for review
PATCH /api/admin/profiles/{user_id}           - Admin profile override
PATCH /api/admin/profiles/{user_id}/onboarding - Override onboarding flags
POST /api/admin/profiles/{user_id}/reset-onboarding - Reset all onboarding
GET  /api/admin/clients/{user_id}/summary     - Get comprehensive client summary

GET  /api/admin/tasks                         - List all tasks (with filters)
POST /api/admin/tasks                         - Create and assign task
PATCH /api/admin/tasks/{task_id}              - Update task
DELETE /api/admin/tasks/{task_id}             - Delete task
POST /api/admin/tasks/trigger-recurring       - Trigger recurring task generation

GET  /api/admin/crm/tasks                     - List CRM tasks
POST /api/admin/crm/tasks                     - Create CRM task
PATCH /api/admin/crm/tasks/{task_id}          - Update CRM task

POST /api/admin/escalate                      - Trigger Luna escalation
POST /api/admin/oscar/complete                - Complete Oscar wizard
POST /api/admin/sync/tasks                    - Sync tasks to frontend
POST /api/admin/sync/profiles                 - Sync profile flags to frontend
```

### Knowledge Base (`/api/kb`)
```
GET  /api/kb/entries                          - List KB entries (with filters)
GET  /api/kb/entries/{entry_id}               - Get specific KB entry
GET  /api/kb/search?query=<text>              - Search KB for Luna responses
```

### Recurring Tasks (`/api/recurring`)
```
GET  /api/recurring/templates                 - List recurring templates
GET  /api/recurring/templates/{id}            - Get specific template
POST /api/recurring/templates                 - Create template
PATCH /api/recurring/templates/{id}           - Update template
DELETE /api/recurring/templates/{id}          - Delete template
GET  /api/recurring/predefined                - List predefined templates
POST /api/recurring/predefined/{key}          - Apply predefined template
POST /api/recurring/trigger                   - Trigger task generation
POST /api/recurring/preview                   - Preview rule occurrences
GET  /api/recurring/summary                   - Get rule summary
```

---

## Data Models

### SetupState (Onboarding)
```json
{
  "welcome_complete": false,
  "fdc_percent_set": false,
  "gst_status_set": false,
  "oscar_intro_seen": false,
  "levy_auto_enabled": false,
  "escalation_pending": null,
  "last_escalation": null
}
```

### RecurringTaskTemplate
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": "Monthly BAS Check",
  "description": "Review BAS before submission",
  "priority": "high",
  "category": "compliance",
  "task_type": "recurring",
  "recurrence_rule": "FREQ=MONTHLY;BYMONTHDAY=21",
  "recurrence_summary": "Monthly on the 21st",
  "is_active": true,
  "last_generated_at": "2025-12-27T00:18:25",
  "next_due_date": "2026-01-21",
  "created_at": "2025-12-27T00:18:11",
  "updated_at": "2025-12-27T00:18:25"
}
```

---

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db?ssl=require
CORS_ORIGINS=*
```

## Related Projects

- **MyFDC Frontend** (Emergent Project ID EMT-663f69)
- **FDC Tax + Knowledge Base** (Emergent Project ID EMT-385e5d)
