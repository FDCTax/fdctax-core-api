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
https://taxcore-crm.preview.emergentagent.com/api/vxt/webhook
```

**Supported Events:** call.completed, call.transcribed, call.recording_ready

**Frontend:** Planned for next phase

### 5. LodgeIT Integration ✅ (Backend - Dec 2025)
**Backend:** `/api/lodgeit/...`
- Export queue management
- Database triggers for automatic queue population
- Audit trail for exports

### 6. Identity Spine v1.1 ✅ (Backend - Dec 2025)
**Backend:** `/api/identity/...`
- Unified person model (email as single source of truth)
- MyFDC account management with automatic person linking
- CRM client management with automatic person linking
- Engagement profile tracking (service flags, subscriptions)
- Identity merging for duplicate resolution
- **Merge Preview & Conflict Detection** (NEW v1.1)
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
- `GET /api/identity/merge-preview` - Preview merge with conflict detection (admin) **(NEW)**
- `POST /api/identity/link-existing` - Link existing records (admin)
- `POST /api/identity/merge` - Merge duplicate persons (admin)

**Merge Preview Conflict Detection:**
- `conflicting_emails` (warning) - Different email addresses
- `multiple_myfdc_accounts` (high) - Both have MyFDC accounts
- `multiple_crm_clients` (high) - Both have CRM clients  
- `mismatched_auth_providers` (medium) - Different auth providers
- `mismatched_service_flags` (low) - Different engagement flags
- `different_contact_info` (low) - Different names/phones

**Database Tables:**
- `person` - Central identity table (email is unique)
- `myfdc_account` - MyFDC account data
- `crm_client_identity` - CRM client data
- `engagement_profile` - Service engagement flags
- `identity_link_log` - Audit trail for identity operations

### 7. BAS Module (Enhanced - Dec 2025)
**Backend:** `/api/bas/...`
- Existing: Save snapshots, history, sign-off, PDF data, change log
- **NEW: Multi-step workflow** (prepare → review → approve → lodge)
- **NEW: Enhanced history** with grouped periods and comparisons

**Workflow Endpoints:**
- `POST /api/bas/workflow/initialize` - Initialize 4-step workflow
- `GET /api/bas/workflow/{bas_id}` - Get workflow status with progress
- `POST /api/bas/workflow/{bas_id}/step/{step}/complete` - Complete step
- `POST /api/bas/workflow/{bas_id}/step/{step}/reject` - Reject step
- `POST /api/bas/workflow/{bas_id}/step/{step}/assign` - Assign step
- `GET /api/bas/workflow/pending/me` - Get user's pending steps

**History Endpoints:**
- `GET /api/bas/history/grouped` - Grouped by quarter/month/year
- `GET /api/bas/history/compare` - Compare with previous/same_last_year

**Database Tables:**
- `bas_statements` - BAS snapshots with versioning
- `bas_change_log` - Audit trail
- `bas_workflow_steps` - **NEW:** Workflow step tracking

### 9. SMS Integration Phase 1 ✅ (Backend - Dec 2025)
**Backend:** `/api/sms/...`
- Real SMS sending via Twilio (when configured)
- Phone number validation and normalization (E.164, Australian formats)
- 9 pre-defined templates for common use cases
- Graceful failure handling when unconfigured
- Message status tracking

**Endpoints:**
- `GET /api/sms/status` - Integration status and config check
- `GET /api/sms/templates` - List available templates
- `POST /api/sms/send` - Send direct SMS
- `POST /api/sms/send-template` - Send from template
- `GET /api/sms/message/{id}` - Get message status
- `POST /api/sms/test` - Test SMS (admin only)

**Templates Available:**
- `appointment_reminder`, `document_request`, `payment_reminder`
- `tax_deadline`, `bas_ready`, `bas_approved`, `bas_lodged`
- `welcome`, `verification_code`

**Environment Variables Required:**
- `SMS_ACCOUNT_SID` - Twilio Account SID
- `SMS_AUTH_TOKEN` - Twilio Auth Token
- `SMS_FROM_NUMBER` - Twilio Phone Number

### 10. Secret Authority Verification Endpoints ✅ (Backend - Jan 2025)
**Backend:** `/api/sa/...`
- Dedicated endpoints for Secret Authority to verify system configuration
- Used to confirm encryption, email, and internal auth are properly configured

**Endpoints:**
- `GET /api/sa/status` - Overall system status (encryption, email, internal auth)
- `GET /api/sa/email/status` - Email module readiness (`{"ready": true/false}`)
- `POST /api/sa/tfn/encrypt` - Encrypt TFN (`{"tfn": "..."} → {"encrypted": "..."}`)
- `POST /api/sa/tfn/decrypt` - Decrypt TFN (`{"encrypted": "..."} → {"tfn": "..."}`)
- `GET /api/sa/internal/status` - Internal auth status (`{"internal_auth_configured": true/false}`)

**Environment Variables Checked:**
- `ENCRYPTION_KEY` - For TFN encryption
- `EMAIL_API_KEY` or `RESEND_API_KEY` - For email
- `INTERNAL_API_KEY` - For internal service auth

### 11. Core Module - Phase 3 Scaffolding ✅ (Backend - Jan 2025)
**Backend:** `/api/core/...`
- 86-field client profile schema with full CRUD
- TFN encryption utilities (ready, awaiting ENCRYPTION_KEY)
- Internal API key authentication for service-to-service calls
- Luna migration endpoints (single, batch, sync, rollback)
- UUID validation on profile lookups

**Endpoints:**
- `GET /api/core/status` - Module status with feature flags
- `POST /api/core/client-profiles` - Create profile (staff, admin)
- `GET /api/core/client-profiles` - List/search profiles
- `GET /api/core/client-profiles/{id}` - Get by ID
- `GET /api/core/client-profiles/by-code/{code}` - Get by code
- `PATCH /api/core/client-profiles/{id}` - Update profile
- `DELETE /api/core/client-profiles/{id}` - Archive profile (admin)
- `POST /api/core/migration/client` - Migrate single client (API key auth)
- `POST /api/core/migration/batch` - Batch migration (API key auth)
- `POST /api/core/migration/sync` - Sync client (API key auth)
- `GET /api/core/migration/status` - Migration stats (API key or admin)
- `POST /api/core/migration/rollback/{batch_id}` - Rollback batch (admin)

**Database Table:** `public.client_profiles` (86 fields)

**Environment Variables Required:**
- `INTERNAL_API_KEY` - For service-to-service auth
- `ENCRYPTION_KEY` - For TFN encryption (optional, recommended)

### 11. Existing Modules
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

- ✅ **Identity Spine v1.1** - Merge Preview & Conflict Detection
  - Read-only merge preview endpoint
  - Conflict detection (emails, accounts, auth providers, flags)
  - Conflict severity levels (high/medium/low/warning)
  - Merge direction recommendation
  - safe_to_merge flag based on high severity conflicts
  - Audit logging for preview requests
  - Full test coverage (51/51 tests passed, no regressions)

- ✅ **BAS Module Enhanced** - Workflow & History
  - Multi-step sign-off workflow (prepare → review → approve → lodge)
  - Workflow step assignment, completion, rejection
  - Pending steps per user/role
  - Grouped history (by quarter/month/year)
  - Period comparison (previous quarter, same last year)
  - Full test coverage (41/42 tests passed, 2 bugs fixed)

- ✅ **SMS Integration Phase 1** - Twilio SMS
  - Real SMS sending via Twilio (when credentials configured)
  - Phone number validation & normalization (Australian formats)
  - 9 pre-defined templates for BAS, appointments, documents
  - Graceful failure when unconfigured (returns 503)
  - Full test coverage (42/42 tests passed)

- ✅ **Client Test User Created**
  - `client@fdctax.com` / `client123` - for workflow testing

### Session 4: Core Module Phase 3 (January 1, 2025)
- ✅ **Core Module Phase 3 - Scaffolding Complete**
  - 86-field `client_profiles` table in `public` schema
  - Client profile CRUD with full field support
  - TFN encryption utilities (`/app/backend/utils/encryption.py`)
  - Internal API key authentication middleware
  - Luna migration endpoints (single, batch, sync, rollback)
  - UUID format validation on profile lookups
  - Full test coverage (42/42 tests passed, minor bug fixed)
  - Internal auth configured via `INTERNAL_API_KEY` env var

### Session 5: Luna Service Migration Phase 4 (January 1, 2025)
- ✅ **Business Logic Migration - Structural Phase**
  - Client validation utilities (ABN, ACN, TFN, email, phone)
  - Australian data normalization (states, phone formats)
  - Entity type and status mapping
  - Client matching/deduplication (`ClientMatcher`)
  - Business rules (`LunaBusinessRules`):
    - GST threshold determination
    - BAS frequency calculation
    - Client tier calculation
    - Required documents by entity type
    - Lodgement readiness validation
  - Migration priority scoring
  - Migration audit logging (`MigrationAuditLogger`)
  - New `/api/core/migration/validate` endpoint for pre-flight checks
  - Enhanced batch migration with priority sorting

- ✅ **Frontend Converted to API-Only Mode**
  - Removed login UI from frontend
  - All routes show "API-only mode" message
  - No session/cookie-based auth
  - Authentication via Internal API Keys only

- ✅ **Deployment Preparation Complete**
  - Fixed .gitignore blocking .env files
  - Removed MongoDB from supervisor config
  - Secret Authority integration ready
  - All secrets injected at runtime (not in .env)

- ✅ **Secret Authority Verification Endpoints**
  - `/api/sa/status` - Overall system status
  - `/api/sa/email/status` - Email module readiness
  - `/api/sa/internal/status` - Internal auth status
  - `/api/sa/tfn/encrypt` - TFN encryption endpoint
  - `/api/sa/tfn/decrypt` - TFN decryption endpoint

- ✅ **Encryption Integration (A3-3)**
  - Enhanced `EncryptionService` class for all sensitive data
  - TFN, ABN, ACN, Bank Details encryption/decryption
  - Field validation before encryption
  - Masking utilities for safe display
  - Batch encrypt/decrypt operations
  - Audit logging (no plaintext in logs)
  - 25 unit tests - all passing

- ✅ **Tax Module Logic Endpoints (A3-4)**
  - POB (Place of Business / Home Office): Fixed rate (67c/hr), actual cost, shortcut
  - Occupancy Expenses: Mortgage interest, council rates, insurance, rent, CGT warnings
  - Depreciation: Diminishing value, prime cost, instant write-off, SB pool
  - Motor Vehicle: Cents per km (85c, max 5000km), logbook method
  - Combined calculation endpoint
  - ATO 2024-25 tax year compliance
  - 26 unit tests - all passing

- ✅ **Core Client API (A3-1.4) - MyFDC Beta Critical Path**
  - `POST /api/clients/link-or-create` - Link or create Core client
  - `GET /api/clients/{client_id}` - Get client by ID
  - `GET /api/clients` - List all clients with filters
  - `POST /api/clients/{client_id}/link-crm` - Link CRM client ID
  - `GET /api/clients/golden/test-client` - Get/create Golden Test Client
  - Deduplication by email and ABN
  - Audit logging (no plaintext TFN/ABN in logs)
  - Internal service token authentication
  - 17 unit tests - all passing

- ✅ **MyFDC Data Intake API (Ticket A3-2) - COMPLETED**
  - `POST /api/myfdc/profile` - Update educator profile (create/update)
  - `POST /api/myfdc/hours` - Log hours worked
  - `POST /api/myfdc/occupancy` - Log occupancy data (children, rooms)
  - `POST /api/myfdc/diary` - Create diary entries
  - `POST /api/myfdc/expense` - Log expenses (with category, GST, business %)
  - `POST /api/myfdc/attendance` - Log child attendance (with CCS hours)
  - `GET /api/myfdc/summary/hours` - Get hours summary for date range
  - `GET /api/myfdc/summary/expenses` - Get expenses summary by category
  - `GET /api/myfdc/status` - Module status check
  - Internal service token authentication (X-Internal-Api-Key)
  - Client existence validation
  - Audit logging (sensitive data excluded)
  - 31 unit tests - all passing

- ✅ **CRM Bookkeeping Data Access API (Ticket A3-3.3) - COMPLETED**
  - `GET /api/bookkeeping/{client_id}/hours` - Hours worked records with totals
  - `GET /api/bookkeeping/{client_id}/occupancy` - Occupancy records with room breakdown
  - `GET /api/bookkeeping/{client_id}/diary` - Diary entries with category filter
  - `GET /api/bookkeeping/{client_id}/expenses` - Expenses with GST/business % breakdown
  - `GET /api/bookkeeping/{client_id}/attendance` - Child attendance with CCS hours
  - `GET /api/bookkeeping/{client_id}/summary` - Combined dashboard summary
  - `GET /api/bookkeeping/status` - Module status check
  - Internal service token authentication (X-Internal-Api-Key)
  - Date range filtering on all endpoints
  - Audit logging for all CRM data access
  - 23 unit tests - all passing

- ✅ **Webhook Notification System (Ticket A3-4) - COMPLETED**
  - `POST /api/webhooks/register` - Register webhook (returns secret key)
  - `GET /api/webhooks` - List all webhooks
  - `GET /api/webhooks/{id}` - Get specific webhook
  - `DELETE /api/webhooks/{id}` - Delete webhook
  - `PUT /api/webhooks/{id}/status` - Enable/disable webhook
  - `GET /api/webhooks/events` - List supported event types
  - `GET /api/webhooks/queue/stats` - Queue statistics
  - `GET /api/webhooks/queue/dead-letter` - Dead letter items
  - `POST /api/webhooks/queue/dead-letter/{id}/retry` - Retry failed delivery
  - `POST /api/webhooks/queue/process` - Manual queue processing
  - HMAC-SHA256 signature (X-Webhook-Signature header)
  - Retry queue with exponential backoff (3 attempts: 1min, 5min, 15min)
  - Dead-letter queue for persistent failures
  - Audit logging for all webhook operations
  - MyFDC intake triggers webhooks automatically
  - 26 unit tests - all passing

**Files Created/Modified:**
- `/app/backend/core/luna_business_logic.py` (NEW)
- `/app/backend/core/migration.py` (Enhanced)
- `/app/backend/core/router.py` (Enhanced)
- `/app/backend/core/__init__.py` (Updated exports)
- `/app/backend/routers/secret_authority.py` (NEW)
- `/app/backend/routers/myfdc_intake.py` (NEW - Ticket A3-2)
- `/app/backend/routers/bookkeeping_access.py` (NEW - Ticket A3-3.3)
- `/app/backend/routers/webhooks.py` (NEW - Ticket A3-4)
- `/app/backend/services/myfdc_intake.py` (Enhanced - Ticket A3-2, A3-4)
- `/app/backend/services/bookkeeping_access.py` (NEW - Ticket A3-3.3)
- `/app/backend/services/webhook_service.py` (NEW - Ticket A3-4)
- `/app/backend/models/myfdc_data.py` (NEW - Ticket A3-2)
- `/app/backend/tests/test_myfdc_intake.py` (NEW - 31 tests)
- `/app/backend/tests/test_bookkeeping_access.py` (NEW - 23 tests)
- `/app/backend/tests/test_webhooks.py` (NEW - 26 tests)
- `/app/backend/create_myfdc_tables.py` (NEW - Migration script)
- `/app/backend/utils/encryption.py` (Enhanced)
- `/app/backend/tests/test_encryption.py` (NEW - 25 tests)
- `/app/frontend/src/App.js` (API-only mode)
- `/app/.gitignore` (Deployment fix)

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

### MyFDC Data Intake Module (NEW - Jan 2025)
```sql
myfdc_educator_profiles: {id UUID PK, client_id FK, educator_name, phone, email, address_*, suburb, state, postcode, abn, service_approval_number, approval_start_date, approval_expiry_date, max_children, qualifications JSONB, first_aid_expiry, wwcc_number, wwcc_expiry, created_at, updated_at, created_by, updated_by}
myfdc_hours_worked: {id UUID PK, client_id FK, work_date, hours, start_time, end_time, notes, created_at, created_by}
myfdc_occupancy: {id UUID PK, client_id FK, occupancy_date, number_of_children, hours_per_day, rooms_used JSONB, room_details JSONB, preschool_program, notes, created_at, created_by}
myfdc_diary_entries: {id UUID PK, client_id FK, entry_date, description, category, child_name, has_photos, photo_count, created_at, created_by}
myfdc_expenses: {id UUID PK, client_id FK, expense_date, amount, category, description, gst_included, tax_deductible, business_percentage, receipt_number, vendor, created_at, created_by}
myfdc_attendance: {id UUID PK, client_id FK, child_name, attendance_date, hours, arrival_time, departure_time, ccs_hours, notes, absent, absence_reason, created_at, created_by}
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

### MyFDC Data Intake (NEW - Jan 2025)
- `POST /api/myfdc/profile` - Update educator profile (Internal Auth)
- `POST /api/myfdc/hours` - Log hours worked (Internal Auth)
- `POST /api/myfdc/occupancy` - Log occupancy data (Internal Auth)
- `POST /api/myfdc/diary` - Create diary entry (Internal Auth)
- `POST /api/myfdc/expense` - Log expense (Internal Auth)
- `POST /api/myfdc/attendance` - Log child attendance (Internal Auth)
- `GET /api/myfdc/summary/hours` - Get hours summary (Internal Auth)
- `GET /api/myfdc/summary/expenses` - Get expenses summary (Internal Auth)
- `GET /api/myfdc/status` - Module status (Internal Auth)

### CRM Bookkeeping Data Access (NEW - Jan 2025)
- `GET /api/bookkeeping/{client_id}/hours` - Hours worked records (Internal Auth)
- `GET /api/bookkeeping/{client_id}/occupancy` - Occupancy records (Internal Auth)
- `GET /api/bookkeeping/{client_id}/diary` - Diary entries (Internal Auth)
- `GET /api/bookkeeping/{client_id}/expenses` - Expense records (Internal Auth)
- `GET /api/bookkeeping/{client_id}/attendance` - Attendance records (Internal Auth)
- `GET /api/bookkeeping/{client_id}/summary` - Combined summary (Internal Auth)
- `GET /api/bookkeeping/status` - Module status (Internal Auth)

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

### P0 - Luna Service Migration Phase 4 (Continued)
1. **Receive Luna field mappings** - Awaiting additional field mapping documentation from user
2. **Implement remaining business logic** - Tax calculation rules, compliance checks
3. **Build sync mechanism** - Real-time or batch sync from Luna to Core
4. **Integration testing** - End-to-end testing with actual Luna data

### P1 - Frontend Development (On Hold)
1. **VXT Phone UI** - Display call logs, transcripts, recordings, workpaper linking
2. **BAS Module UI** - Display BAS history, change logs, sign-off workflow

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
│   ├── test_identity_spine.py  # Identity Spine tests (30 tests)
│   └── test_myfdc_intake.py    # MyFDC Intake tests (31 tests)
└── test_reports/               # Test results
```

---

*Last Updated: January 2, 2025*
