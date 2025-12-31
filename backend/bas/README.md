# BAS Module

## Overview

This module provides Business Activity Statement (BAS) functionality for the FDC Tax Core application, including GST calculations, BAS preparation, versioning, and audit trails.

**Current Status:** Phase 0+ (Foundation implemented, calculator stub)

## Module Structure

```
/app/backend/bas/
├── __init__.py          # Module exports
├── models.py            # SQLAlchemy database models (IMPLEMENTED)
├── service.py           # Business logic layer (IMPLEMENTED)
├── bas_calculator.py    # GST/BAS calculation engine (STUB)
├── bas_schema.py        # Schema definitions & Pydantic models
└── README.md            # This file

/app/backend/routers/
└── bas.py               # API endpoints (IMPLEMENTED)
```

## Implementation Status

### ✅ Implemented (Previous Session)
- **Database Models:** `bas_statements`, `bas_change_log` tables
- **Service Layer:** Save, history, sign-off, PDF data generation
- **API Endpoints:** Full CRUD + change log + PDF

### 🔲 Stub/Placeholder (Phase 0)
- **BAS Calculator:** GST calculation from transactions
- **Validation:** Transaction validation for BAS
- **Reconciliation:** Variance checking

## Phases

### Phase 0: Foundation ✅
- Database schema for BAS statements
- Versioning and audit trail
- Basic CRUD operations
- Stub calculator

### Phase 1: Calculation Engine (Future)
- GST calculation from transactions
- BAS field aggregation
- Multi-currency support
- Rounding rules (ATO compliant)

### Phase 2: Advanced Features (Future)
- PAYG integration
- Fuel tax credits
- Wine equalisation tax
- Luxury car tax

### Phase 3: ATO Integration (Future)
- SBR (Standard Business Reporting) export
- LodgeIT integration
- Lodgement tracking

## API Endpoints

### Implemented

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/bas/status` | Module status |
| POST | `/api/bas/save` | Save BAS snapshot |
| GET | `/api/bas/history` | Get BAS history |
| GET | `/api/bas/{id}` | Get single BAS |
| POST | `/api/bas/{id}/sign-off` | Sign off BAS |
| POST | `/api/bas/{id}/pdf` | Generate PDF data |
| POST | `/api/bas/change-log` | Log change |
| GET | `/api/bas/change-log/entries` | Get change log |

### Stub (Phase 0)

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| POST | `/api/bas/validate` | Validate transactions | Stub |
| POST | `/api/bas/calculate` | Calculate BAS | Stub |

## Environment Variables

```bash
# BAS Configuration
BAS_PROVIDER=            # Future: ATO integration provider
BAS_API_KEY=             # Future: Provider API key
BAS_FEATURE_FLAG=true    # Feature flag for BAS module
```

## Database Schema

### bas_statements (Implemented)
```sql
CREATE TABLE bas_statements (
    id UUID PRIMARY KEY,
    client_id VARCHAR(36) NOT NULL,
    job_id VARCHAR(36),
    period_from DATE NOT NULL,
    period_to DATE NOT NULL,
    g1_total_income NUMERIC(14,2),
    gst_on_income_1a NUMERIC(14,2),
    gst_on_expenses_1b NUMERIC(14,2),
    net_gst NUMERIC(14,2),
    -- ... additional fields
    version INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'draft',
    created_at TIMESTAMP WITH TIME ZONE
);
```

### bas_change_log (Implemented)
```sql
CREATE TABLE bas_change_log (
    id UUID PRIMARY KEY,
    bas_statement_id UUID,
    client_id VARCHAR(36) NOT NULL,
    user_id VARCHAR(36) NOT NULL,
    action_type VARCHAR(50),
    entity_type VARCHAR(50),
    old_value JSONB,
    new_value JSONB,
    timestamp TIMESTAMP WITH TIME ZONE
);
```

## Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Transaction │────▶│    BAS      │────▶│    BAS      │
│   Engine    │     │ Calculator  │     │  Statement  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           │                   ▼
                           │            ┌─────────────┐
                           │            │  Change Log │
                           │            └─────────────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   LodgeIT   │     │     PDF     │
                    │   Export    │     │  Generation │
                    └─────────────┘     └─────────────┘
```

## Integration Points

### CRM Module
- Client information for BAS preparation
- ABN/GST registration status

### Workpapers Module
- Period context for BAS calculations
- Transaction categorization

### Transaction Engine
- Source data for GST calculations
- GST code assignments

### LodgeIT Module
- BAS export for lodgement
- Lodgement status tracking

## BAS Field Reference

### GST Fields (ATO)
| Field | Description |
|-------|-------------|
| G1 | Total sales (including GST) |
| G2 | Export sales |
| G3 | Other GST-free sales |
| G10 | Capital purchases |
| G11 | Non-capital purchases |
| 1A | GST on sales |
| 1B | GST on purchases |

### Calculation
```
Net GST = 1A - 1B
Total Payable = Net GST + PAYG Instalment
```

## RBAC Permissions

| Role | View | Create | Sign-off | Delete |
|------|------|--------|----------|--------|
| admin | ✅ | ✅ | ✅ | ✅ |
| staff | ✅ | ✅ | ✅ | ❌ |
| tax_agent | ✅ | ✅ | ✅ | ❌ |
| client | ✅ (own) | ❌ | ❌ | ❌ |

## Usage Examples

### Save BAS Snapshot
```python
POST /api/bas/save
{
    "client_id": "client-001",
    "period_from": "2024-07-01",
    "period_to": "2024-09-30",
    "summary": {
        "g1_total_income": 100000.00,
        "gst_on_income_1a": 9090.91,
        "gst_on_expenses_1b": 5454.55,
        "net_gst": 3636.36,
        "total_payable": 3636.36
    },
    "status": "draft"
}
```

### Sign Off BAS
```python
POST /api/bas/{bas_id}/sign-off
{
    "review_notes": "Reviewed and approved for lodgement"
}
```

### Get Change Log
```python
GET /api/bas/change-log/entries?client_id=client-001&limit=50
```

## Security Considerations

1. **Audit Trail**: All changes logged with user, timestamp, old/new values
2. **Versioning**: BAS statements are versioned, not overwritten
3. **Sign-off**: Irreversible once signed off
4. **RBAC**: Role-based access to BAS functions

## Handoff Notes

- Calculator module is a stub - implement GST logic in Phase 1
- Use `BASCalculator.calculate()` as the entry point
- Follow ATO rounding rules (round to nearest cent)
- GST rate is 10% for Australia

---

*Last Updated: December 31, 2025*
*Phase: 0 - Foundation + Stubs*
