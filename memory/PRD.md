# FDC Tax Core + CRM Sync - Product Requirements Document

## Project Overview
FDC Tax Core is a comprehensive tax management and bookkeeping platform designed for tax accountants and bookkeepers. The application provides tools for managing clients, workpapers, transactions, and various integrations for tax-related workflows.

## Core Features

### 1. Authentication & Authorization
- JWT-based authentication with access/refresh tokens
- Role-based access control (RBAC): admin, staff (bookkeeper), tax_agent, client
- Audit logging for all authentication events

### 2. Bookkeeping Ingestion System ✅ (NEW - Dec 2025)
**Backend:** `/api/ingestion/...`
- File upload for CSV/Excel bank statements
- Automatic column detection and mapping suggestions
- Duplicate transaction detection
- Batch rollback capability
- Import audit trail

**Frontend:** `/ingestion` route
- Multi-step import wizard (Upload → Map Columns → Import → Complete)
- Drag-and-drop file upload
- Interactive column mapping with preview
- Import history with rollback functionality
- Role-based access (admin, staff have write; tax_agent has read-only)

### 3. BAS (Business Activity Statement) Module ✅ (Backend Only - Dec 2025)
**Backend:** `/api/bas/...`
- BAS statement versioning and history
- Sign-off workflow with user tracking
- Change audit log
- PDF data generation endpoint

**Frontend:** Planned for next phase

### 4. VXT Phone Integration ✅ (Production Ready - Dec 2025)
**Backend:** `/api/vxt/...`
- Webhook handler for VXT phone system (signature validated)
- Call data storage (from/to numbers, duration, etc.)
- Transcript and recording storage
- Automatic client matching via phone number (exact match)
- Workpaper auto-linking when client matched
- Call recording streaming

**Production Webhook URL:**
```
https://fdccore-taxcrm.preview.emergentagent.com/api/vxt/webhook
```

**Supported Events:** call.completed, call.transcribed, call.recording_ready

**Frontend:** Planned for next phase

### 5. LodgeIT Integration ✅ (Backend - Dec 2025)
**Backend:** `/api/lodgeit/...`
- Export queue management
- Database triggers for automatic queue population
- Audit trail for exports

### 6. Identity Spine v1 ✅ (Backend - Dec 2025)
**Backend:** `/api/identity/...`
- Unified person model (email as single source of truth)
- MyFDC account management with automatic person linking
- CRM client management with automatic person linking
- Engagement profile tracking (service flags, subscriptions)
- Identity merging for duplicate resolution
- Orphan detection and cleanup
- Admin statistics and audit logging

**Key Endpoints:**
- `POST /api/identity/myfdc-signup` - Public MyFDC signup
- `POST /api/identity/crm-client-create` - Create CRM client (staff)
- `GET /api/identity/person/by-email` - Lookup by email (staff)
- `GET /api/identity/person/{id}` - Lookup by ID (staff)
- `PUT /api/identity/engagement/{id}` - Update engagement flags (staff)
- `GET /api/identity/stats` - Identity statistics (admin)
- `GET /api/identity/orphaned` - Orphaned records (admin)
- `POST /api/identity/link-existing` - Link existing records (admin)
- `POST /api/identity/merge` - Merge duplicate persons (admin)

**Database Tables:**
- `person` - Central identity table (email is unique)
- `myfdc_account` - MyFDC account data
- `crm_client_identity` - CRM client data
- `engagement_profile` - Service engagement flags
- `identity_link_log` - Audit trail for identity operations

### 7. Existing Modules
- CRM/Clients Management
- Workpaper Management
- Transaction Engine
- Motor Vehicle Logbook
- Calendly Integration
- Document Management
- Recurring Tasks

---

## Tech Stack
- **Backend:** FastAPI (Python)
- **Frontend:** React 19 + Tailwind CSS + Shadcn/UI
- **Database:** PostgreSQL
- **Authentication:** JWT with RBAC

---

## Implemented Features (December 2025)

### Session 1: Backend Foundation
- ✅ LodgeIT Backend Integration
- ✅ Bookkeeping Ingestion System (Backend)
- ✅ BAS Backend Foundations
- ✅ VXT Phone System Integration (Backend)
- ✅ Pre-Deployment Hardening

### Session 2: Frontend Development
- ✅ **Bookkeeping Ingestion UI**
  - Login/Authentication flow
  - Multi-step import wizard
  - File upload with drag-and-drop
  - Column mapping interface
  - Import progress and results
  - History tab with batch list
  - Rollback functionality

### Session 3: Backend Modules (December 31, 2025)
- ✅ **Identity Spine v1** - Unified identity management
  - Person model (email as primary identifier)
  - MyFDC account management
  - CRM client management  
  - Automatic linking (same email = same person)
  - Engagement profile tracking
  - Admin tools: stats, orphan detection, merge
  - Full test coverage (30/30 tests passed)

---

## Database Schema (Key Tables)

### Identity Module (NEW - Dec 2025)
```sql
person: {id UUID PK, email UNIQUE, first_name, last_name, mobile, phone, date_of_birth, status, email_verified, mobile_verified, metadata JSONB, created_at, updated_at}
myfdc_account: {id UUID PK, person_id FK, username, password_hash, auth_provider, auth_provider_id, settings JSONB, preferences JSONB, onboarding_completed, status, created_at, updated_at}
crm_client_identity: {id UUID PK, person_id FK, client_code UNIQUE, abn, business_name, entity_type, gst_registered, tags JSONB, custom_fields JSONB, status, created_at, updated_at}
engagement_profile: {id UUID PK, person_id FK, is_myfdc_user, is_crm_client, has_ocr, is_diy_bas_user, subscription_tier, created_at, updated_at}
identity_link_log: {id UUID PK, person_id FK, action, source_type, source_id, target_type, target_id, performed_by, details JSONB, created_at}
```

### Ingestion Module
```sql
import_batches: {id, client_id, job_id, file_name, file_type, status, row_count, imported_count, skipped_count, error_count, column_mapping, errors, uploaded_by, uploaded_at}
import_audit_log: {id, batch_id, user_id, action, details, timestamp}
```

### BAS Module
```sql
bas_statements: {id, client_id, period_from, period_to, total_payable, status, version, completed_by, signed_off_at}
bas_change_log: {id, bas_statement_id, user_id, action_type, old_value, new_value, timestamp}
```

### VXT Module
```sql
vxt_calls: {id, call_id, from_number, to_number, matched_client_id, duration, direction, status}
vxt_transcripts: {id, call_id, transcript_text, summary_text}
vxt_recordings: {id, call_id, recording_url}
workpapers_call_links: {id, call_id, workpaper_id}
```

---

## API Endpoints Summary

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/refresh` - Refresh token
- `GET /api/auth/me` - Get current user

### Ingestion
- `POST /api/ingestion/upload` - Upload file
- `POST /api/ingestion/parse` - Parse file and get preview
- `POST /api/ingestion/import` - Import transactions
- `POST /api/ingestion/rollback` - Rollback batch
- `GET /api/ingestion/batches` - List batches
- `GET /api/ingestion/batches/{id}` - Get batch details
- `GET /api/ingestion/batches/{id}/audit-log` - Get audit log

### BAS
- `POST /api/bas/save-snapshot` - Save BAS snapshot
- `GET /api/bas/history/{client_id}` - Get BAS history
- `POST /api/bas/sign-off/{statement_id}` - Sign off statement
- `GET /api/bas/change-log/{statement_id}` - Get change log

### VXT
- `POST /api/vxt/webhook` - Handle VXT webhook
- `GET /api/vxt/calls` - List calls
- `GET /api/vxt/calls/{call_id}` - Get call details
- `POST /api/vxt/link-workpaper` - Link call to workpaper

### Identity
- `GET /api/identity/status` - Module status (public)
- `POST /api/identity/myfdc-signup` - MyFDC signup (public)
- `POST /api/identity/crm-client-create` - Create CRM client (staff)
- `GET /api/identity/person/by-email` - Lookup by email (staff)
- `GET /api/identity/person/{id}` - Lookup by ID (staff)
- `PUT /api/identity/engagement/{id}` - Update engagement (staff)
- `GET /api/identity/stats` - Statistics (admin)
- `GET /api/identity/orphaned` - Orphaned records (admin)
- `GET /api/identity/duplicates` - Duplicate emails (admin)
- `POST /api/identity/link-existing` - Link records (admin)
- `POST /api/identity/merge` - Merge persons (admin)

---

## Test Credentials
- **Admin:** admin@fdctax.com / admin123
- **Staff:** staff@fdctax.com / staff123
- **Tax Agent:** taxagent@fdctax.com / taxagent123
- **Client:** client@fdctax.com / client123

---

## Known Issues & Blockers

### P1: Database Migration Permissions
The `fdccore` database user lacks `ALTER TABLE` privileges on certain tables. Schema migrations require admin intervention or `.sql` scripts to be run manually.

**Workaround:** Migration scripts are generated in `/app/backend/migrations/` for admin to run.

---

## Upcoming Tasks

### P1 - Frontend Development
1. **BAS Module UI** - Display BAS history, change logs, sign-off workflow
2. **VXT Phone UI** - Display call logs, transcripts, recordings, workpaper linking

### P2 - Database Migrations
1. Deprecate old `workpaper_transactions` table
2. Migrate legacy file-based services to PostgreSQL

### P3 - Infrastructure
1. Cloud storage for documents (S3)
2. Enhanced error tracking with Sentry

---

## File Structure

```
/app/
├── backend/
│   ├── bas/                    # BAS module
│   ├── identity/               # Identity Spine module (NEW)
│   │   ├── __init__.py
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   ├── router.py           # API endpoints
│   │   └── service.py          # Business logic
│   ├── ingestion/              # Ingestion module
│   ├── vxt/                    # VXT module
│   ├── lodgeit_integration/    # LodgeIT module
│   ├── email_integration/      # Email module (blocked by API key)
│   ├── sms_integration/        # SMS module (scaffolded)
│   ├── routers/                # API routers
│   ├── migrations/             # SQL migration scripts
│   └── server.py               # Main FastAPI app
├── frontend/
│   ├── src/
│   │   ├── components/ui/      # Shadcn components
│   │   ├── context/            # React contexts
│   │   ├── lib/                # Utilities & API client
│   │   └── pages/              # Page components
│   └── package.json
├── tests/                      # Test files
│   └── test_identity_spine.py  # Identity Spine tests (30 tests)
└── test_reports/               # Test results
```

---

*Last Updated: December 31, 2025*
