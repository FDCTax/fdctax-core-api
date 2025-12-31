# Email Integration Module

## Overview

This module provides email functionality for the FDC Tax Core application, enabling automated and manual email communications with clients.

**Current Status:** Phase 0 - Scaffolding Complete

## Module Structure

```
/app/backend/email_integration/
├── __init__.py          # Module exports
├── email_client.py      # Provider interface (stub)
├── email_sender.py      # High-level service (stub)
├── email_schema.py      # Database schema placeholder
├── email_router.py      # API endpoints
└── README.md            # This file
```

## Phases

### Phase 0: Scaffolding (Current) ✅
- Module structure created
- Stub classes and methods
- Environment variable placeholders
- API endpoint stubs
- Documentation

### Phase 1: Provider Integration (Future)
- Resend SDK integration
- Outbound email sending
- Delivery status tracking
- Basic error handling

### Phase 2: Templates & Bulk (Future)
- Email templates with variables
- Template management API
- Bulk email sending
- Queue system for scheduled sends

### Phase 3: Automation (Future)
- Appointment reminders
- Document request notifications
- Tax deadline alerts
- Payment reminders
- Open/click tracking

## Environment Variables

Add these to `/app/backend/.env`:

```bash
# Email Integration
EMAIL_PROVIDER=resend           # Provider: resend, sendgrid, ses, smtp
EMAIL_API_KEY=                  # Provider API key
EMAIL_FROM_ADDRESS=             # Default sender (e.g., noreply@fdctax.com.au)
EMAIL_FEATURE_FLAG=true         # Enable/disable email features
```

## API Endpoints

### Current (Phase 0)

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| GET | `/api/email/status` | Module status | Live |
| POST | `/api/email/send` | Send email | Stub (not_implemented) |
| POST | `/api/email/validate` | Validate email | Stub (not_implemented) |

### Future (Phase 1+)

| Method | Endpoint | Description | Phase |
|--------|----------|-------------|-------|
| POST | `/api/email/send` | Send email | 1 |
| POST | `/api/email/send-bulk` | Send bulk emails | 2 |
| POST | `/api/email/send-template` | Send from template | 2 |
| GET | `/api/email/logs` | List sent emails | 2 |
| GET | `/api/email/logs/{id}` | Get email details | 2 |
| GET | `/api/email/templates` | List templates | 2 |
| POST | `/api/email/templates` | Create template | 2 |
| GET | `/api/email/stats` | Get email statistics | 3 |

## Provider Options

### Resend (Recommended)
- Modern API, excellent DX
- Australian data residency available
- Good deliverability
- Generous free tier (3,000/month)
- Pricing: ~$0.001 per email

### SendGrid
- Enterprise-grade
- Extensive features
- Template builder
- Pricing: ~$0.001-0.003 per email

### AWS SES
- Cost-effective at scale
- Requires AWS setup
- Pricing: ~$0.0001 per email

### SMTP (Generic)
- Works with any SMTP server
- More setup required
- Good for self-hosted solutions

## Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Trigger   │────▶│   Email     │────▶│   Email     │
│   (API/Job) │     │   Sender    │     │   Client    │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                           │                   ▼
                           │            ┌─────────────┐
                           │            │  Provider   │
                           │            │  (Resend)   │
                           │            └─────────────┘
                           │                   │
                           ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐
                    │  Audit Log  │     │  Recipient  │
                    └─────────────┘     └─────────────┘
```

## Integration Points

### CRM Module
- Client email addresses
- Contact preferences
- Communication history

### SMS Module
- Fallback notifications
- Multi-channel messaging

### VXT Phone Module
- Call follow-up emails
- Voicemail transcripts

### Workpapers Module
- Document request emails
- Status notifications
- Completion alerts

### BAS Module
- BAS completion notifications
- Deadline reminders

## Database Schema (Future - Phase 2)

```sql
-- email_logs
CREATE TABLE email_logs (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100) UNIQUE,
    to_address VARCHAR(255) NOT NULL,
    from_address VARCHAR(255) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    provider VARCHAR(30) DEFAULT 'resend',
    provider_message_id VARCHAR(100),
    status VARCHAR(30) DEFAULT 'pending',
    client_id VARCHAR(36),
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## RBAC Permissions

| Role | Send Email | View Logs | Manage Templates |
|------|------------|-----------|------------------|
| admin | ✅ | ✅ | ✅ |
| staff | ✅ | ✅ | ❌ |
| tax_agent | ✅ | ✅ (own clients) | ❌ |
| client | ❌ | ❌ | ❌ |

## Usage Examples

### Sending Email (Phase 1)

```python
from email_integration import EmailClient, EmailSender

# Initialize
client = EmailClient()
sender = EmailSender(client)

# Send simple email
result = sender.send(
    to="client@example.com",
    subject="Your Tax Return is Ready",
    body="<p>Hi John, your tax return has been completed.</p>",
    client_id="client-001"
)

# Send from template
result = sender.send_from_template(
    to="client@example.com",
    template_id="tax_return_ready",
    variables={
        "client_name": "John",
        "tax_year": "2024",
        "amount": "$2,500 refund"
    }
)
```

### API Request (Phase 1)

```bash
curl -X POST https://your-domain/api/email/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "client@example.com",
    "subject": "Test Email",
    "body": "<p>Hello!</p>",
    "client_id": "client-001"
  }'
```

## Security Considerations

1. **API Keys**: Never commit EMAIL_API_KEY to version control
2. **Rate Limiting**: Implement per-user and global rate limits
3. **Validation**: Validate all email addresses before sending
4. **Audit Trail**: Log all sent emails for compliance
5. **PII**: Email addresses are PII - handle appropriately
6. **Unsubscribe**: Include unsubscribe links in marketing emails

## Pre-defined Templates

| Template ID | Use Case |
|-------------|----------|
| `appointment_reminder` | Appointment reminders |
| `document_request` | Request documents from client |
| `tax_return_ready` | Notify client tax return is complete |
| `invoice` | Send invoice |

## Handoff Notes for Phase 1

1. **Resend SDK**: `pip install resend`
2. **API Key**: Get from https://resend.com/api-keys
3. **Domain Verification**: Add DNS records for custom domain
4. **Entry Point**: `EmailClient.send_email()`
5. **Error Handling**: Resend raises `resend.Error` on failures
6. **Testing**: Use Resend test API key for development

---

*Last Updated: December 31, 2025*
*Phase: 0 - Scaffolding*
