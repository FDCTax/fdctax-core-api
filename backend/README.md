# FDC Tax Core + CRM Sync API

Backend API for FDC Tax CRM sync, user onboarding state, Meet Oscar wizard integration, recurring tasks, document uploads, and authentication.

## Overview

This API connects the MyFDC frontend to the internal CRM system, providing:
- **JWT Authentication** - Secure login with role-based access control
- User profile and onboarding state management
- Meet Oscar wizard integration
- Task management and CRM sync
- Recurring Task Engine - Automatic task generation
- Document Upload Request System
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

## Authentication & Authorization

The API uses JWT (JSON Web Tokens) for authentication with role-based access control.

### Roles

| Role | Description | Access |
|------|-------------|--------|
| `admin` | Full system access | All endpoints |
| `staff` | White-glove service team (bookkeeper) | Admin + user endpoints, edit transactions until LOCKED |
| `tax_agent` | Tax practitioner | Read-only in Bookkeeper Tab, can lock for workpapers |
| `client` | FDC educator/client | User endpoints + MyFDC sync only |

### Authentication Flow

```
1. Login with email/password
   POST /api/auth/login → returns access_token + refresh_token

2. Use access_token for API requests
   Authorization: Bearer <access_token>

3. When access_token expires (1 hour), use refresh_token
   POST /api/auth/refresh → returns new tokens

4. Refresh token expires in 7 days, requiring re-login
```

### API Endpoints

#### Public Endpoints

```bash
# Login
POST /api/auth/login
Content-Type: application/json
{
  "email": "admin@fdctax.com",
  "password": "admin123"
}

# Response
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user_id": "uuid",
  "email": "admin@fdctax.com",
  "role": "admin"
}

# Refresh token
POST /api/auth/refresh?refresh_token=<token>

# Register (client role only)
POST /api/auth/register
{
  "email": "new@example.com",
  "password": "password123",
  "first_name": "John",
  "last_name": "Doe"
}

# Verify token
GET /api/auth/verify
Authorization: Bearer <token>
```

#### Authenticated Endpoints

```bash
# Get current user info
GET /api/auth/me
Authorization: Bearer <token>

# Change password
POST /api/auth/change-password
Authorization: Bearer <token>
{
  "current_password": "old123",
  "new_password": "new123"
}

# Logout
POST /api/auth/logout
Authorization: Bearer <token>
```

#### Admin-Only Endpoints

```bash
# Register user with any role
POST /api/auth/admin/register
Authorization: Bearer <admin_token>
{
  "email": "staff@fdctax.com",
  "password": "staff123",
  "first_name": "Staff",
  "last_name": "User",
  "role": "staff"
}

# Set user role
PATCH /api/auth/admin/users/{user_id}/role?role=staff
Authorization: Bearer <admin_token>

# Set user password
POST /api/auth/admin/users/{user_id}/set-password?new_password=newpass
Authorization: Bearer <admin_token>

# List role assignments
GET /api/auth/admin/roles
Authorization: Bearer <admin_token>

# Add admin email
POST /api/auth/admin/roles/add-admin?email=newadmin@fdctax.com
Authorization: Bearer <admin_token>

# Add staff email
POST /api/auth/admin/roles/add-staff?email=newstaff@fdctax.com
Authorization: Bearer <admin_token>
```

### Test Users

Seed test users for development:

```bash
POST /api/auth/seed-test-users?admin_key=fdc-seed-2025
```

| Email | Password | Role |
|-------|----------|------|
| admin@fdctax.com | admin123 | admin |
| staff@fdctax.com | staff123 | staff |
| taxagent@fdctax.com | taxagent123 | tax_agent |
| client@fdctax.com | client123 | client |

### Using Authentication in Requests

```bash
# 1. Login
TOKEN=$(curl -s -X POST "http://localhost:8001/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@fdctax.com", "password": "admin123"}' \
  | jq -r '.access_token')

# 2. Use token in requests
curl -s "http://localhost:8001/api/admin/users" \
  -H "Authorization: Bearer $TOKEN"
```

### Token Expiry

| Token Type | Expiry | Usage |
|------------|--------|-------|
| Access Token | 1 hour | API requests |
| Refresh Token | 7 days | Get new access token |

### Environment Variables

```env
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
```

---

## Unified Transaction Engine + Bookkeeper Layer

The Transaction Engine is the **single source of truth** for all financial transactions in the FDC system. It provides a canonical ledger with full audit trail, role-based access control, and integration points for MyFDC client submissions, bank imports, and workpaper modules.

### Key Features

- **Canonical Ledger**: All transactions flow through a single `transactions` table
- **Dual-Column Design**: Client fields (raw) + Bookkeeper fields (reviewed) for every transaction
- **Full Audit Trail**: Every change recorded in `transaction_history`
- **RBAC Enforcement**: Role-based permissions at endpoint and field level
- **Workpaper Locking**: Transactions locked when consumed by workpapers
- **Bulk Operations**: Atomic bulk updates with single history entry

### Database Schema

#### transactions Table
```sql
CREATE TABLE transactions (
    id UUID PRIMARY KEY,
    client_id VARCHAR NOT NULL,
    date DATE NOT NULL,
    amount DECIMAL(18,2) NOT NULL,
    -- Client fields (raw from MyFDC)
    payee_raw VARCHAR,
    description_raw VARCHAR,
    source transaction_source_enum,  -- BANK, MYFDC, OCR, MANUAL
    category_client VARCHAR,
    module_hint_client VARCHAR,
    notes_client TEXT,
    -- Bookkeeper fields (reviewed/overridden)
    category_bookkeeper VARCHAR,
    gst_code_bookkeeper gst_code_enum,
    notes_bookkeeper TEXT,
    status_bookkeeper transaction_status_enum,  -- NEW, PENDING, REVIEWED, READY_FOR_WORKPAPER, EXCLUDED, LOCKED
    flags JSONB,  -- {late: bool, duplicate: bool, high_risk: bool}
    module_routing module_routing_enum,  -- MOTOR_VEHICLE, HOME_OCCUPANCY, etc.
    -- Lock state
    locked_at TIMESTAMP,
    locked_by_role VARCHAR,
    -- Timestamps
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

#### transaction_history Table
```sql
CREATE TABLE transaction_history (
    id UUID PRIMARY KEY,
    transaction_id UUID REFERENCES transactions(id),
    user_id UUID,
    role VARCHAR,
    action_type history_action_type_enum,  -- manual, bulk_recode, import, myfdc_create, lock, unlock, etc.
    before_state JSONB,
    after_state JSONB,
    comment TEXT,
    created_at TIMESTAMP
);
```

### RBAC Permissions Matrix

| Endpoint | client | staff | tax_agent | admin |
|----------|--------|-------|-----------|-------|
| `GET /api/bookkeeper/transactions` | ❌ | ✔️ | ✔️ (read-only) | ✔️ |
| `PATCH /api/bookkeeper/transactions/{id}` | ❌ | ✔️* | ❌ | ✔️ |
| `POST /api/bookkeeper/transactions/bulk-update` | ❌ | ✔️ | ❌ | ✔️ |
| `GET /api/bookkeeper/transactions/{id}/history` | ❌ | ✔️ | ✔️ | ✔️ |
| `POST /api/workpapers/transactions-lock` | ❌ | ❌ | ✔️ | ✔️ |
| `POST /api/bookkeeper/transactions/{id}/unlock` | ❌ | ❌ | ❌ | ✔️ |
| `POST /api/myfdc/transactions` | ✔️ | ❌ | ❌ | ✔️ |
| `PATCH /api/myfdc/transactions/{id}` | ✔️ | ❌ | ❌ | ✔️ |

*Staff can edit unless status=LOCKED (then only `notes_bookkeeper`)

### Role Behaviours

**Staff (Bookkeeper)**
- Can edit any field until status = LOCKED
- Cannot unlock transactions
- Cannot modify locked transactions except `notes_bookkeeper`
- Cannot call workpaper lock endpoint

**Tax Agent**
- Read-only access in Bookkeeper Tab
- Can lock transactions via workpaper engine
- Cannot unlock (admin only)

**Admin**
- Full access to all endpoints
- Can override any field including locked transactions
- Unlock requires comment (minimum 10 characters)

**Client (MyFDC)**
- Can create/update their own transactions via `/api/myfdc/*`
- Cannot access Bookkeeper Tab endpoints
- Updates rejected when status ≥ REVIEWED

### API Endpoints

#### Bookkeeper Tab (`/api/bookkeeper`)

```bash
# List transactions with filters
GET /api/bookkeeper/transactions
  ?client_id=<uuid>
  &status=NEW|PENDING|REVIEWED|READY_FOR_WORKPAPER|EXCLUDED|LOCKED
  &date_from=2024-01-01
  &date_to=2024-12-31
  &category=travel
  &source=BANK|MYFDC|OCR|MANUAL
  &module_routing=MOTOR_VEHICLE|HOME_OCCUPANCY|GENERAL
  &flags=late,duplicate,high_risk
  &search=keyword
  &cursor=<cursor>
  &limit=50

# Get single transaction
GET /api/bookkeeper/transactions/{id}

# Update transaction (bookkeeper edit)
PATCH /api/bookkeeper/transactions/{id}
{
  "category_bookkeeper": "Motor Vehicle",
  "gst_code_bookkeeper": "GST",
  "notes_bookkeeper": "Verified receipt",
  "status_bookkeeper": "REVIEWED",
  "module_routing": "MOTOR_VEHICLE",
  "flags": {"late": false, "duplicate": false}
}

# Bulk update
POST /api/bookkeeper/transactions/bulk-update
{
  "criteria": {
    "client_id": "uuid",
    "status": "NEW",
    "transaction_ids": ["uuid1", "uuid2"]
  },
  "updates": {
    "category_bookkeeper": "General Expenses",
    "status_bookkeeper": "REVIEWED"
  }
}

# Get audit trail
GET /api/bookkeeper/transactions/{id}/history

# Admin unlock (requires comment ≥10 chars)
POST /api/bookkeeper/transactions/{id}/unlock?comment=Reopening%20for%20correction
```

#### Workpaper Lock (`/api/workpapers`)

```bash
# Lock transactions for workpaper (tax_agent, admin only)
POST /api/workpapers/transactions-lock
{
  "transaction_ids": ["uuid1", "uuid2"],
  "workpaper_id": "job-uuid",
  "module": "MOTOR_VEHICLE",
  "period": "2024-25"
}

# Response
{
  "success": true,
  "locked_count": 2,
  "total_requested": 2,
  "workpaper_id": "job-uuid",
  "module": "MOTOR_VEHICLE",
  "period": "2024-25"
}
```

#### MyFDC Sync (`/api/myfdc`)

```bash
# Create transaction from client app
POST /api/myfdc/transactions?client_id=<client_id>
{
  "date": "2024-12-15",
  "amount": 150.50,
  "payee": "Office Supplies",
  "description": "Printer paper and toner",
  "category": "Office Expenses",
  "module_hint": "GENERAL",
  "notes": "Quarterly supply order"
}

# Update transaction from client app
# Rejected if status ≥ REVIEWED
PATCH /api/myfdc/transactions/{id}
{
  "amount": 155.00,
  "notes": "Updated amount"
}
```

#### Import (`/api/import`)

```bash
# Bulk import bank transactions (staff, admin)
POST /api/import/bank?client_id=<client_id>
[
  {"date": "2024-12-01", "amount": 100, "payee": "Vendor A"},
  {"date": "2024-12-02", "amount": 200, "payee": "Vendor B"}
]

# Bulk import OCR transactions (staff, admin)
POST /api/import/ocr?client_id=<client_id>
[...]
```

#### Reference Data

```bash
GET /api/bookkeeper/statuses      # Transaction status enum values
GET /api/bookkeeper/gst-codes     # GST code enum values
GET /api/bookkeeper/sources       # Transaction source enum values
GET /api/bookkeeper/module-routings  # Module routing enum values
```

### Status Hierarchy

```
NEW → PENDING → REVIEWED → READY_FOR_WORKPAPER → LOCKED
                    ↘ EXCLUDED (branch)
```

When status = LOCKED:
- Transaction is consumed by a workpaper module
- Only `notes_bookkeeper` editable (by staff)
- Admin can unlock with comment

### Locking Workflow

1. **Prepare**: Staff reviews transactions, sets status to READY_FOR_WORKPAPER
2. **Lock**: Tax agent calls `/api/workpapers/transactions-lock`
3. **Snapshot**: System captures bookkeeper fields at lock time
4. **Consume**: Workpaper module reads locked transactions
5. **Unlock** (if needed): Admin unlocks with mandatory comment

### Example Workflow

```bash
# 1. Login as staff
TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"staff@fdctax.com","password":"staff123"}' \
  | jq -r '.access_token')

# 2. List unreviewed transactions
curl -s "$API_URL/api/bookkeeper/transactions?status=NEW&client_id=test-client" \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. Review a transaction
curl -s -X PATCH "$API_URL/api/bookkeeper/transactions/{id}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "category_bookkeeper": "Motor Vehicle",
    "gst_code_bookkeeper": "GST",
    "status_bookkeeper": "REVIEWED",
    "module_routing": "MOTOR_VEHICLE"
  }' | jq

# 4. Bulk update multiple transactions
curl -s -X POST "$API_URL/api/bookkeeper/transactions/bulk-update" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "criteria": {"client_id": "test-client", "status": "NEW"},
    "updates": {"status_bookkeeper": "PENDING"}
  }' | jq

# 5. Login as tax_agent to lock for workpaper
TAX_TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"taxagent@fdctax.com","password":"taxagent123"}' \
  | jq -r '.access_token')

# 6. Lock transactions for workpaper
curl -s -X POST "$API_URL/api/workpapers/transactions-lock" \
  -H "Authorization: Bearer $TAX_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_ids": ["uuid1", "uuid2"],
    "workpaper_id": "workpaper-job-uuid",
    "module": "MOTOR_VEHICLE",
    "period": "2024-25"
  }' | jq
```

### Files

| File | Description |
|------|-------------|
| `/app/backend/database/transaction_models.py` | SQLAlchemy models |
| `/app/backend/services/transaction_service.py` | Business logic |
| `/app/backend/routers/bookkeeper.py` | API router |
| `/app/backend/middleware/auth.py` | RBAC decorators |
| `/app/backend/tests/test_transaction_engine.py` | Transaction tests |
| `/app/backend/tests/test_transaction_engine_rbac.py` | RBAC tests |

---

## Document Upload Request System

Request and receive documents from clients.

### Endpoints

```bash
# User endpoints
GET /api/documents/user?user_id=<uuid>
GET /api/documents/user/pending?user_id=<uuid>
GET /api/documents/user/count?user_id=<uuid>
POST /api/documents/user/upload (multipart/form-data)

# Admin endpoints
GET /api/documents/admin
POST /api/documents/admin/request
PATCH /api/documents/admin/{id}
POST /api/documents/admin/{id}/dismiss
DELETE /api/documents/admin/{id}

# Utilities
GET /api/documents/types
GET /api/documents/stats
GET /api/documents/overdue
GET /api/documents/audit
```

---

## Recurring Task Engine

Automatic task generation based on iCal RRULE format.

### RRULE Examples

| Pattern | RRULE |
|---------|-------|
| Monthly on 28th | `FREQ=MONTHLY;BYMONTHDAY=28` |
| Quarterly BAS | `FREQ=MONTHLY;BYMONTH=1,4,7,10;BYMONTHDAY=28` |
| Weekly Friday | `FREQ=WEEKLY;BYDAY=FR` |

### Endpoints

```bash
GET /api/recurring/templates
POST /api/recurring/templates
POST /api/recurring/predefined/{key}?user_id=<uuid>
POST /api/admin/tasks/trigger-recurring
POST /api/recurring/preview?rule=<rrule>
```

---

## Audit Logging System

A centralized audit logging system that tracks all significant user and system actions for compliance, debugging, and security monitoring.

### Features

- **Comprehensive Tracking**: Logs all authentication, task, document, and recurring task actions
- **IP & User Agent Capture**: Records request metadata for security analysis
- **Flexible Querying**: Filter logs by user, action type, resource, date range, success status
- **Statistics**: Aggregate views of system activity
- **JSONL Storage**: Efficient append-only log file (can migrate to DB when permissions allow)

### Logged Actions

| Category | Actions |
|----------|---------|
| **Authentication** | `user.login`, `user.login_failed`, `user.logout`, `user.register`, `user.password_change`, `user.password_reset`, `token.refresh` |
| **User Management** | `user.role_change`, `user.update`, `user.deactivate`, `user.activate` |
| **Tasks** | `task.create`, `task.update`, `task.delete`, `task.complete`, `task.assign` |
| **CRM Tasks** | `crm_task.create`, `crm_task.update`, `crm_task.delete` |
| **Documents** | `document.request_create`, `document.upload`, `document.request_dismiss`, `document.download`, `document.delete` |
| **Recurring** | `recurring.template_create`, `recurring.trigger`, `recurring.task_generated` |
| **Profile** | `profile.update`, `onboarding.update`, `oscar.toggle` |

### Audit Log Schema

```json
{
  "id": "uuid",
  "timestamp": "2025-01-15T10:30:00.000Z",
  "user_id": "user-uuid",
  "user_email": "admin@fdctax.com",
  "action": "user.login",
  "resource_type": "auth",
  "resource_id": null,
  "details": {
    "role": "admin"
  },
  "ip_address": "192.168.1.100",
  "user_agent": "Mozilla/5.0...",
  "success": true,
  "error_message": null
}
```

### Sample Log Entries

**Successful Login:**
```json
{
  "action": "user.login",
  "resource_type": "auth",
  "user_email": "admin@fdctax.com",
  "details": {"role": "admin"},
  "success": true
}
```

**Failed Login:**
```json
{
  "action": "user.login_failed",
  "resource_type": "auth",
  "user_email": "unknown@example.com",
  "details": {"reason": "Invalid email or password"},
  "success": false,
  "error_message": "Invalid credentials"
}
```

**Task Created:**
```json
{
  "action": "task.create",
  "resource_type": "task",
  "resource_id": "task-uuid",
  "user_id": "admin-uuid",
  "details": {
    "task_name": "Review BAS",
    "assigned_to_user": "client-uuid",
    "due_date": "2025-01-30",
    "priority": "high"
  },
  "success": true
}
```

**Document Uploaded:**
```json
{
  "action": "document.upload",
  "resource_type": "document",
  "resource_id": "request-uuid",
  "user_id": "client-uuid",
  "details": {
    "file_name": "tax_return_2024.pdf",
    "file_size": 1024000,
    "content_type": "application/pdf"
  },
  "success": true
}
```

### API Endpoints

```bash
# List audit logs with filters (staff/admin only)
GET /api/audit
  ?start_date=2025-01-01
  &end_date=2025-01-31
  &user_id=<uuid>
  &action=user.login
  &resource_type=auth
  &success=true
  &limit=100
  &offset=0

# Get single audit entry
GET /api/audit/entry/{entry_id}

# Get audit statistics
GET /api/audit/stats

# Get user activity
GET /api/audit/user/{user_id}?limit=50

# Get resource history
GET /api/audit/resource/{resource_type}/{resource_id}?limit=50

# Get failed actions
GET /api/audit/errors?limit=100

# List available action types
GET /api/audit/actions

# Cleanup old logs (admin only, keep last N days)
POST /api/audit/cleanup?days_to_keep=90

# Get current user's own activity
GET /api/audit/my-activity?limit=50
```

### Usage Examples

```bash
# 1. Login and get token
TOKEN=$(curl -s -X POST "http://localhost:8001/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@fdctax.com", "password": "admin123"}' \
  | jq -r '.access_token')

# 2. Get all audit logs
curl -s "http://localhost:8001/api/audit" \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. Get login events only
curl -s "http://localhost:8001/api/audit?action=user.login" \
  -H "Authorization: Bearer $TOKEN" | jq

# 4. Get failed actions
curl -s "http://localhost:8001/api/audit/errors" \
  -H "Authorization: Bearer $TOKEN" | jq

# 5. Get audit statistics
curl -s "http://localhost:8001/api/audit/stats" \
  -H "Authorization: Bearer $TOKEN" | jq

# 6. Get activity for a specific user
curl -s "http://localhost:8001/api/audit/user/<user-uuid>" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Storage

Audit logs are stored in `/app/backend/data/audit_log.jsonl` using JSON Lines format for efficient appending. Each line is a valid JSON object representing one log entry.

**Note:** This file-based storage is a workaround for the sandbox DB permission limitations. When DB permissions are available, logs can be migrated to a PostgreSQL table for better querying and scalability.

---

## Luna Escalation System

Luna AI can escalate complex queries to the FDC Tax team when confidence is low or human review is needed.

### Escalation Flow

```
1. User asks Luna a question
2. Luna detects low confidence or complex query
3. Luna calls POST /api/luna/escalate with context
4. System creates:
   - Task for client in myfdc.user_tasks
   - Escalation record with metadata
   - Audit log entry
5. FDC Tax staff reviews via /api/luna/escalations
6. Staff resolves and updates status
```

### Create Escalation

```bash
POST /api/luna/escalate
Content-Type: application/json

{
  "client_id": "uuid-of-client",
  "query": "What if I use my car for both daycare and personal errands?",
  "luna_response": "This may be partially deductible. Let me flag this for review.",
  "confidence": 0.42,
  "tags": ["motor_vehicle", "mixed_use"],
  "priority": "medium",
  "additional_context": "Client mentioned 60% business use"
}
```

**Response:**
```json
{
  "success": true,
  "escalation_id": "uuid",
  "task_id": "uuid",
  "client_id": "uuid",
  "message": "Escalation created. FDC Tax team will review within 24-48 hours.",
  "confidence": 0.42,
  "priority": "medium",
  "tags": ["motor_vehicle", "mixed_use"]
}
```

### Priority Levels

| Priority | Description | Response Time |
|----------|-------------|---------------|
| `low` | Non-urgent, general questions | 5 days |
| `medium` | Standard escalation | 2 days |
| `high` | Complex or time-sensitive | 1 day |
| `urgent` | Immediate attention needed | 1 day (highest) |

### Confidence Score Behavior

- **0.0-0.3**: Very low confidence → auto-escalates as high priority
- **0.3-0.5**: Low confidence → standard escalation
- **0.5-1.0**: Moderate confidence → review requested

### Available Tags

```
motor_vehicle, mixed_use, home_office, travel, meals_entertainment,
equipment, depreciation, gst, bas, eofy, complex_deduction,
contractor, employee, superannuation, investment, capital_gains, other
```

### Escalation Statuses

| Status | Description |
|--------|-------------|
| `open` | New escalation, not yet reviewed |
| `in_review` | Staff member is working on it |
| `resolved` | Issue has been addressed |
| `dismissed` | Not actionable or duplicate |

### Admin Review Endpoints

```bash
# List all escalations (staff/admin)
GET /api/luna/escalations
GET /api/luna/escalations?status=open
GET /api/luna/escalations?max_confidence=0.5
GET /api/luna/escalations?tag=motor_vehicle
GET /api/luna/escalations?priority=high

# Get escalation statistics
GET /api/luna/escalations/stats

# Get specific escalation
GET /api/luna/escalations/{escalation_id}

# Update escalation status
PATCH /api/luna/escalations/{escalation_id}/status?status=resolved&resolution_notes=Advised%20on%20logbook%20method

# Assign to staff member
PATCH /api/luna/escalations/{escalation_id}/assign?assigned_to=staff@fdctax.com

# Get client's escalation history
GET /api/luna/escalations/client/{client_id}

# List available tags and priorities
GET /api/luna/tags
GET /api/luna/priorities
GET /api/luna/statuses
```

### Example: Complete Escalation Workflow

```bash
# 1. Login as admin
TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@fdctax.com", "password": "admin123"}' \
  | jq -r '.access_token')

# 2. Create an escalation (simulating Luna)
curl -s -X POST "$API_URL/api/luna/escalate" \
  -H "Content-Type: application/json" \
  -d '{
    "client_id": "dab5bbb9-76ad-4a0d-850d-9508660e6af1",
    "query": "Can I claim my home internet as a deduction?",
    "luna_response": "Home internet may be partially deductible for business use. Let me flag this for review.",
    "confidence": 0.38,
    "tags": ["home_office", "mixed_use"]
  }' | jq

# 3. List open escalations
curl -s "$API_URL/api/luna/escalations?status=open" \
  -H "Authorization: Bearer $TOKEN" | jq

# 4. Pick up escalation for review
curl -s -X PATCH "$API_URL/api/luna/escalations/{escalation_id}/status?status=in_review" \
  -H "Authorization: Bearer $TOKEN" | jq

# 5. Resolve escalation
curl -s -X PATCH "$API_URL/api/luna/escalations/{escalation_id}/status?status=resolved&resolution_notes=Advised%20on%20work%20percentage%20calculation" \
  -H "Authorization: Bearer $TOKEN" | jq

# 6. Check escalation stats
curl -s "$API_URL/api/luna/escalations/stats" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Task Created by Escalation

When an escalation is created, a task is added to `myfdc.user_tasks` with:

- **Title**: `Luna Escalation: [truncated query]`
- **Description**: Full context including query, Luna's response, confidence, tags
- **Priority**: Based on confidence and requested priority
- **Category**: `escalation`
- **Task Type**: `luna_escalation`
- **Due Date**: 1-5 days based on priority

### Audit Logging

All escalations are logged to the centralized audit system:

```json
{
  "action": "luna.escalation",
  "resource_type": "task",
  "resource_id": "task-uuid",
  "details": {
    "escalation_id": "uuid",
    "client_id": "uuid",
    "query": "User's question...",
    "luna_response": "Luna's response...",
    "confidence": 0.42,
    "tags": ["motor_vehicle", "mixed_use"],
    "priority": "medium"
  }
}
```

---

## API Endpoints Summary

### Health (`/api`)
- `GET /` - Health check
- `GET /health` - Detailed status

### Authentication (`/api/auth`)
- `POST /login` - Login
- `POST /refresh` - Refresh token
- `POST /register` - Register (client)
- `GET /me` - Current user info
- `POST /change-password` - Change password
- `POST /logout` - Logout
- `GET /verify` - Verify token
- `POST /admin/register` - Admin register
- `PATCH /admin/users/{id}/role` - Set role
- `POST /admin/users/{id}/set-password` - Set password
- `GET /admin/roles` - List roles
- `POST /admin/roles/add-admin` - Add admin
- `POST /admin/roles/add-staff` - Add staff
- `POST /admin/roles/add-tax-agent` - Add tax agent
- `POST /seed-test-users` - Seed test data

### Bookkeeper Transactions (`/api/bookkeeper`) - NEW
- `GET /transactions` - List with filters and pagination
- `GET /transactions/{id}` - Get single transaction
- `PATCH /transactions/{id}` - Update transaction (RBAC enforced)
- `POST /transactions/bulk-update` - Atomic bulk update
- `GET /transactions/{id}/history` - Audit trail
- `POST /transactions/{id}/unlock` - Admin unlock (admin only)
- `GET /statuses` - Transaction status enum
- `GET /gst-codes` - GST code enum
- `GET /sources` - Transaction source enum
- `GET /module-routings` - Module routing enum

### Workpaper Transactions (`/api/workpapers`) - NEW
- `POST /transactions-lock` - Lock for workpaper (tax_agent, admin)

### MyFDC Sync (`/api/myfdc`) - NEW
- `POST /transactions` - Create transaction (client, admin)
- `PATCH /transactions/{id}` - Update transaction (client, admin)

### Import (`/api/import`) - NEW
- `POST /bank` - Bulk import bank transactions (staff, admin)
- `POST /ocr` - Bulk import OCR transactions (staff, admin)

### User (`/api/user`)
- `GET /tasks` - User's tasks
- `GET /profile` - Profile + setup state
- `POST /profile` - Update profile
- `POST /oscar` - Toggle Oscar
- `PATCH /onboarding` - Update onboarding
- `GET /onboarding/status` - Get setup state
- `GET /documents` - Document requests

### Admin (`/api/admin`)
- User management
- Profile management
- Task management
- CRM tasks
- Luna escalation
- Oscar wizard
- CRM sync
- Recurring task trigger

### Documents (`/api/documents`)
- User document requests
- File upload
- Admin management
- Audit logs

### Knowledge Base (`/api/kb`)
- Entry management
- Search

### Recurring Tasks (`/api/recurring`)
- Template management
- Predefined templates
- Task generation

### Audit Logs (`/api/audit`)
- `GET /` - List audit logs (with filters)
- `GET /entry/{id}` - Get specific entry
- `GET /stats` - Get statistics
- `GET /user/{user_id}` - User activity
- `GET /resource/{type}/{id}` - Resource history
- `GET /errors` - Failed actions
- `GET /actions` - List action types
- `POST /cleanup` - Cleanup old logs
- `GET /my-activity` - Own activity

### Luna Escalations (`/api/luna`)
- `POST /escalate` - Create escalation from Luna
- `GET /escalations` - List escalations (with filters)
- `GET /escalations/stats` - Escalation statistics
- `GET /escalations/{id}` - Get specific escalation
- `PATCH /escalations/{id}/status` - Update status
- `PATCH /escalations/{id}/assign` - Assign to staff
- `GET /escalations/client/{id}` - Client's escalations
- `GET /tags` - Available tags
- `GET /priorities` - Priority levels
- `GET /statuses` - Status options

### Integrations (`/api/integrations`)
- `POST /calendly/webhook` - Receive Calendly events
- `GET /calendly/status` - Check Calendly connection

### Appointments (`/api/appointments`)
- `GET /admin` - List all appointments
- `GET /admin/stats` - Appointment statistics
- `GET /admin/upcoming` - Upcoming appointments
- `GET /admin/{id}` - Get specific appointment
- `PATCH /admin/{id}/status` - Update status
- `POST /admin/create` - Create manual appointment
- `GET /client/{id}` - Client's appointments
- `GET /my-appointments` - Current user's appointments
- `GET /statuses` - Available statuses

---

## Calendly Webhook Integration

Integrates Calendly appointments with the CRM for visibility, task creation, and audit logging.

### Features

- **Webhook Processing**: Automatically receives booking events from Calendly
- **Client Matching**: Maps invitee email to existing clients
- **Task Creation**: Creates CRM tasks for upcoming appointments
- **Audit Logging**: All appointment events are logged
- **Status Management**: Track appointments through their lifecycle

### Webhook Setup

1. Go to [Calendly Developer Portal](https://developer.calendly.com/)
2. Create a webhook subscription:
   - **URL**: `{your-domain}/api/integrations/calendly/webhook`
   - **Events**: `invitee.created`, `invitee.canceled`
3. (Optional) Set a signing key for signature validation

### Webhook Payload Example

```json
{
  "event": "invitee.created",
  "payload": {
    "invitee": {
      "email": "client@example.com",
      "name": "John Smith",
      "uri": "https://api.calendly.com/scheduled_events/.../invitees/...",
      "questions_and_answers": [
        {"question": "What topics would you like to discuss?", "answer": "BAS lodgement"}
      ]
    },
    "event": {
      "uri": "https://api.calendly.com/scheduled_events/...",
      "name": "Tax Consultation",
      "start_time": "2025-01-15T10:00:00Z",
      "end_time": "2025-01-15T10:30:00Z"
    },
    "scheduled_event": {
      "uri": "https://api.calendly.com/scheduled_events/...",
      "name": "Tax Consultation",
      "start_time": "2025-01-15T10:00:00Z",
      "end_time": "2025-01-15T10:30:00Z",
      "location": {
        "type": "google_meet",
        "join_url": "https://meet.google.com/..."
      }
    }
  }
}
```

### Appointment Record Schema

```json
{
  "id": "uuid",
  "calendly_event_uri": "https://api.calendly.com/scheduled_events/...",
  "client_id": "uuid (if matched)",
  "client_email": "client@example.com",
  "client_name": "John Smith",
  "event_type": "Tax Consultation",
  "event_type_name": "Tax Consultation",
  "scheduled_for": "2025-01-15T10:00:00Z",
  "end_time": "2025-01-15T10:30:00Z",
  "duration_minutes": 30,
  "location": "https://meet.google.com/...",
  "location_type": "google_meet",
  "meeting_url": "https://meet.google.com/...",
  "status": "scheduled",
  "task_id": "uuid (if CRM task created)",
  "questions_and_answers": [...],
  "created_at": "2025-01-10T08:00:00Z"
}
```

### Appointment Statuses

| Status | Description |
|--------|-------------|
| `scheduled` | Appointment is booked and upcoming |
| `completed` | Appointment has been completed |
| `cancelled` | Appointment was cancelled |
| `no_show` | Client did not show up |
| `rescheduled` | Appointment was rescheduled |

### API Endpoints

```bash
# Webhook (called by Calendly)
POST /api/integrations/calendly/webhook

# Check Calendly integration status
GET /api/integrations/calendly/status

# List all appointments (admin)
GET /api/appointments/admin
GET /api/appointments/admin?status=scheduled
GET /api/appointments/admin?client_id=uuid
GET /api/appointments/admin?start_date=2025-01-01&end_date=2025-01-31

# Get appointment statistics
GET /api/appointments/admin/stats

# Get upcoming appointments (next N days)
GET /api/appointments/admin/upcoming?days=7

# Get specific appointment
GET /api/appointments/admin/{appointment_id}

# Update appointment status
PATCH /api/appointments/admin/{appointment_id}/status?status=completed

# Get client's appointments
GET /api/appointments/client/{client_id}

# Get current user's appointments
GET /api/appointments/my-appointments

# Create manual appointment (not from Calendly)
POST /api/appointments/admin/create?client_email=...&event_type=...&scheduled_for=...

# List appointment statuses
GET /api/appointments/statuses
```

### Example Workflow

```bash
# 1. Login
TOKEN=$(curl -s -X POST "$API_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@fdctax.com", "password": "admin123"}' \
  | jq -r '.access_token')

# 2. Check Calendly connection
curl -s "$API_URL/api/integrations/calendly/status" \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. Simulate webhook (for testing)
curl -s -X POST "$API_URL/api/integrations/calendly/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "invitee.created",
    "payload": {
      "invitee": {
        "email": "client@example.com",
        "name": "Test Client"
      },
      "scheduled_event": {
        "uri": "https://api.calendly.com/scheduled_events/test-123",
        "name": "Tax Consultation",
        "start_time": "2025-01-20T14:00:00Z",
        "end_time": "2025-01-20T14:30:00Z",
        "location": {"type": "phone"}
      }
    }
  }' | jq

# 4. List all appointments
curl -s "$API_URL/api/appointments/admin" \
  -H "Authorization: Bearer $TOKEN" | jq

# 5. Get appointment statistics
curl -s "$API_URL/api/appointments/admin/stats" \
  -H "Authorization: Bearer $TOKEN" | jq

# 6. Mark appointment as completed
curl -s -X PATCH "$API_URL/api/appointments/admin/{appointment_id}/status?status=completed" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### CRM Task Created

When an appointment is booked and the client is matched:

- **Title**: `Upcoming: {Event Type} with {Client Name}`
- **Description**: Full context including date, time, location, Q&A
- **Due Date**: Appointment date
- **Category**: `appointment`
- **Task Type**: `calendly_appointment`
- **Status**: `pending`

### Audit Logging

All appointment events are logged:

```json
{
  "action": "appointment.booked",
  "resource_type": "appointment",
  "resource_id": "appointment-uuid",
  "details": {
    "event_type": "Tax Consultation",
    "scheduled_for": "2025-01-15T10:00:00Z",
    "client_name": "John Smith",
    "location_type": "google_meet",
    "task_created": true
  }
}
```

### Storage

Appointments stored in `/app/backend/data/appointments.json` (file-based workaround due to DB constraints).

### Environment Variables

```env
CALENDLY_PAT=your-personal-access-token
CALENDLY_WEBHOOK_SECRET=your-webhook-signing-key (optional)
```

---

## Environment Variables

```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db?ssl=require

# CORS
CORS_ORIGINS=*

# JWT Authentication
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Calendly Integration
CALENDLY_PAT=your-calendly-personal-access-token
CALENDLY_WEBHOOK_SECRET=your-webhook-signing-key
```

## Total Endpoints: 110+

---

## 🛡️ Stability Guardrail: Transaction Engine

> **The Transaction Engine is now a stable, unified ledger.**
> 
> - Do **NOT** rename ORM classes, tables, or enums without a dedicated refactor ticket
> - Do **NOT** modify schema fields without architectural approval
> - All future modules (Home Occupancy, Utilities, Internet, etc.) **MUST** consume this engine as-is
> - Database models: `BookkeeperTransactionDB`, `TransactionHistoryDB`, `TransactionAttachmentDB`, `TransactionWorkpaperLinkDB`

---

## Related Projects

- **MyFDC Frontend** (Emergent Project ID EMT-663f69)
- **FDC Tax + Knowledge Base** (Emergent Project ID EMT-385e5d)
