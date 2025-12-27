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
| `staff` | White-glove service team | Admin + user endpoints |
| `client` | FDC educator/client | User endpoints only |

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
| client@example.com | client123 | client |

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
- `POST /seed-test-users` - Seed test data

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
```

## Total Endpoints: 60

## Related Projects

- **MyFDC Frontend** (Emergent Project ID EMT-663f69)
- **FDC Tax + Knowledge Base** (Emergent Project ID EMT-385e5d)
