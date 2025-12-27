# FDC Tax Core + CRM Sync API

Backend API for FDC Tax CRM sync, user onboarding state, Meet Oscar wizard integration, recurring tasks, and document upload requests.

## Overview

This API connects the MyFDC frontend to the internal CRM system, providing:
- User profile and onboarding state management
- Meet Oscar wizard integration
- Task management and CRM sync
- **Recurring Task Engine** - Automatic task generation based on iCal RRULE
- **Document Upload Request System** - Request and receive documents from clients
- Knowledge base access for Luna AI
- White-glove service layer for FDC Tax team

## Quick Start

```bash
cd /app/backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# API Documentation
open http://localhost:8001/docs
```

---

## Document Upload Request System

The document system allows FDC Tax to request documents from clients (tax returns, lease agreements, etc.) and receive secure uploads via MyFDC.

### Features
- Create document requests for clients
- Secure file uploads with checksum verification
- Full audit logging for compliance
- Document type categorization
- Overdue tracking
- Admin management interface

### API Endpoints

#### User Endpoints (`/api/documents/user`)

```bash
# Get all document requests for a user
GET /api/documents/user?user_id=<uuid>
GET /api/documents/user?user_id=<uuid>&status=pending

# Get only pending documents
GET /api/documents/user/pending?user_id=<uuid>

# Get pending count (for notification badges)
GET /api/documents/user/count?user_id=<uuid>

# Upload a document
POST /api/documents/user/upload
Content-Type: multipart/form-data
- user_id: <uuid>
- request_id: <uuid>
- file: <file>
```

#### Admin Endpoints (`/api/documents/admin`)

```bash
# List all document requests (with filters)
GET /api/documents/admin
GET /api/documents/admin?client_id=<uuid>&status=pending&document_type=Tax%20Return

# Get specific request
GET /api/documents/admin/{request_id}

# Create new document request
POST /api/documents/admin/request?created_by=<admin_id>
Content-Type: application/json
{
  "client_id": "user-uuid",
  "title": "2024 Tax Return",
  "description": "Please upload your 2024 tax return",
  "document_type": "Tax Return",
  "due_date": "2025-01-15"
}

# Update a request
PATCH /api/documents/admin/{request_id}?updated_by=<admin_id>
{
  "title": "Updated Title",
  "due_date": "2025-01-20"
}

# Dismiss a request
POST /api/documents/admin/{request_id}/dismiss?dismissed_by=<admin_id>&reason=<reason>

# Delete a request (permanent)
DELETE /api/documents/admin/{request_id}
```

#### Utility Endpoints

```bash
# Get available document types
GET /api/documents/types

# Get statistics
GET /api/documents/stats

# Get overdue requests
GET /api/documents/overdue

# Get audit logs
GET /api/documents/audit
GET /api/documents/audit?request_id=<uuid>&client_id=<uuid>&action=file_uploaded
```

### Document Types

| Type | Key |
|------|-----|
| Tax Return | `tax_return` |
| BAS Statement | `bas_statement` |
| Lease Agreement | `lease_agreement` |
| Insurance Policy | `insurance_policy` |
| Bank Statement | `bank_statement` |
| Receipt | `receipt` |
| Invoice | `invoice` |
| Identity Document | `identity_document` |
| Business Registration | `business_registration` |
| Vehicle Registration | `vehicle_registration` |
| Logbook | `logbook` |
| Other | `other` |

### Document Request Status

| Status | Description |
|--------|-------------|
| `pending` | Awaiting upload from client |
| `uploaded` | Document has been uploaded |
| `dismissed` | Request was cancelled/no longer needed |
| `expired` | Past due date without upload |

### Example: Create and Complete Document Request

```bash
# 1. Admin creates request
curl -X POST "http://localhost:8001/api/documents/admin/request" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "1185602f-d78e-4a55-92c4-8a87d5f9714e",
    "title": "2024 Tax Return",
    "description": "Please upload your 2024 tax return for review",
    "document_type": "Tax Return",
    "due_date": "2025-01-15"
  }'

# 2. Client views pending requests
curl "http://localhost:8001/api/documents/user/pending?user_id=1185602f-d78e-4a55-92c4-8a87d5f9714e"

# 3. Client uploads document
curl -X POST "http://localhost:8001/api/documents/user/upload" \
  -F "user_id=1185602f-d78e-4a55-92c4-8a87d5f9714e" \
  -F "request_id=<request-id>" \
  -F "file=@tax_return_2024.pdf"

# 4. Admin reviews uploaded document
curl "http://localhost:8001/api/documents/admin?status=uploaded"
```

### Audit Logging

All document operations are logged for compliance:
- `request_created` - New document request created
- `request_updated` - Request details modified
- `request_dismissed` - Request was dismissed
- `file_uploaded` - File uploaded with checksum
- `file_downloaded` - File accessed
- `file_deleted` - File removed

```bash
# View audit trail for a request
curl "http://localhost:8001/api/documents/audit?request_id=<uuid>"
```

---

## Recurring Task Engine

Automatically generates tasks based on iCal RRULE recurrence rules (BAS reminders, income prompts, etc.).

### RRULE Examples

| Pattern | RRULE |
|---------|-------|
| Monthly on 28th | `FREQ=MONTHLY;BYMONTHDAY=28` |
| Quarterly BAS | `FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=28` |
| Weekly Friday | `FREQ=WEEKLY;BYDAY=FR` |
| Yearly June 30 | `FREQ=YEARLY;BYMONTH=6;BYMONTHDAY=30` |

### Endpoints

```bash
# List templates
GET /api/recurring/templates

# Create template
POST /api/recurring/templates
{
  "user_id": "uuid",
  "title": "Monthly BAS Check",
  "recurrence_rule": "FREQ=MONTHLY;BYMONTHDAY=21"
}

# Apply predefined template
POST /api/recurring/predefined/quarterly_bas_submission?user_id=<uuid>

# Trigger generation (for cron)
POST /api/admin/tasks/trigger-recurring

# Preview rule
POST /api/recurring/preview?rule=FREQ%3DMONTHLY%3BBYMONTHDAY%3D28
```

---

## API Endpoints Summary

### Health (`/api`)
- `GET /` - Health check
- `GET /health` - Detailed status

### User (`/api/user`)
- `GET /tasks` - User's tasks
- `GET /profile` - Profile + setup state
- `POST /profile` - Update profile
- `POST /oscar` - Toggle Oscar
- `PATCH /onboarding` - Update onboarding flags
- `GET /onboarding/status` - Get setup state
- `GET /documents` - User's document requests

### Admin (`/api/admin`)
- User management (CRUD)
- Profile override
- Task management
- CRM task management
- Luna escalation
- Oscar wizard
- CRM sync
- Recurring task trigger

### Documents (`/api/documents`)
- User document requests
- File upload
- Admin request management
- Document types
- Statistics
- Audit logs

### Knowledge Base (`/api/kb`)
- Entry management
- Search

### Recurring Tasks (`/api/recurring`)
- Template management
- Predefined templates
- Task generation
- Rule preview/summary

---

## File Storage

Currently uses local file storage at `/app/backend/data/uploads/`.
Files are organized by client ID for easy management.

**S3 Migration**: The `FileStorage` class in `services/documents.py` is designed
for easy migration to S3 - replace the `save_file` and `get_file_path` methods.

---

## Environment Variables

```env
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db?ssl=require
CORS_ORIGINS=*
```

## Related Projects

- **MyFDC Frontend** (Emergent Project ID EMT-663f69)
- **FDC Tax + Knowledge Base** (Emergent Project ID EMT-385e5d)
