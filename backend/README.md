# FDC Tax Core + CRM Sync API

Backend API for FDC Tax CRM sync, user onboarding state, and Meet Oscar wizard integration.

## Overview

This API connects the MyFDC frontend to the internal CRM system, providing:
- User profile and onboarding state management
- Meet Oscar wizard integration
- Task management and CRM sync
- Knowledge base access for Luna AI
- White-glove service layer for FDC Tax team

## Database

The API connects to the FDC Tax PostgreSQL sandbox database with the following schemas:
- `myfdc` - Main application tables (users, user_tasks, user_settings, luna_knowledge_base)
- `crm` - Internal CRM tables (tasks, messages)

## API Endpoints

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

#### User Management
```
GET  /api/admin/users                         - List all users (with filters)
GET  /api/admin/users/{user_id}               - Get specific user
GET  /api/admin/users/email/{email}           - Get user by email
PATCH /api/admin/users/{user_id}              - Update user details
```

#### Profile Management
```
GET  /api/admin/profiles/{user_id}            - Get user profile for review
PATCH /api/admin/profiles/{user_id}           - Admin profile override
PATCH /api/admin/profiles/{user_id}/onboarding - Override onboarding flags
POST /api/admin/profiles/{user_id}/reset-onboarding - Reset all onboarding
GET  /api/admin/clients/{user_id}/summary     - Get comprehensive client summary
```

#### Task Management (myfdc.user_tasks)
```
GET  /api/admin/tasks                         - List all tasks (with filters)
POST /api/admin/tasks                         - Create and assign task
PATCH /api/admin/tasks/{task_id}              - Update task
DELETE /api/admin/tasks/{task_id}             - Delete task
```

#### CRM Tasks (crm.tasks)
```
GET  /api/admin/crm/tasks                     - List CRM tasks
POST /api/admin/crm/tasks                     - Create CRM task
PATCH /api/admin/crm/tasks/{task_id}          - Update CRM task
```

#### Escalation & Oscar
```
POST /api/admin/escalate                      - Trigger Luna escalation
POST /api/admin/oscar/complete                - Complete Oscar wizard
```

#### CRM Sync
```
POST /api/admin/sync/tasks                    - Sync tasks to frontend
POST /api/admin/sync/profiles                 - Sync profile flags to frontend
```

### Knowledge Base (`/api/kb`)
```
GET  /api/kb/entries                          - List KB entries (with filters)
GET  /api/kb/entries/{entry_id}               - Get specific KB entry
GET  /api/kb/search?query=<text>              - Search KB for Luna responses
```

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

### UserProfile
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "fdc_percent": 80.0,
  "gst_registered": true,
  "gst_cycle": "quarterly",
  "oscar_enabled": false,
  "levy_auto_enabled": false,
  "setup_state": { ... },
  "created_at": "2025-12-26T00:00:00",
  "updated_at": "2025-12-26T00:00:00"
}
```

### Task
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "task_name": "Review quarterly BAS",
  "description": "Please review your BAS...",
  "due_date": "2025-12-31",
  "status": "pending",
  "priority": "high",
  "category": "compliance",
  "task_type": "internal_crm",
  "created_at": "2025-12-26T00:00:00",
  "updated_at": null
}
```

## Meet Oscar Wizard Flow

1. **Intro Screen**: "Oscar reads receipts for you — snap and go!"
2. **Toggle**: "Enable Preprocessing?" → saves to `user_profiles.oscar_enabled`
3. **Demo**: Optional walkthrough of Quicksnap
4. **Finish**: Returns to dashboard with `oscar_intro_seen: true`

### API Usage:
```bash
# Toggle Oscar and mark intro as seen
POST /api/user/oscar?user_id=<uuid>
Content-Type: application/json
{"enabled": true}

# Or use the wizard completion endpoint
POST /api/admin/oscar/complete?user_id=<uuid>&oscar_enabled=true
```

## Luna Escalation

When Luna detects a complex situation, trigger an escalation:

```bash
POST /api/admin/escalate?user_id=<uuid>&reason=Complex%20GST%20situation
```

This creates:
- A high-priority task for the FDC Tax team
- Sets `escalation_pending: true` in setup_state
- Records `last_escalation` timestamp

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db?ssl=require
CORS_ORIGINS=*
```

## Running the Server

```bash
cd /app/backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

## Related Projects

- **MyFDC Frontend** (Emergent Project ID EMT-663f69)
- **FDC Tax + Knowledge Base** (Emergent Project ID EMT-385e5d)
