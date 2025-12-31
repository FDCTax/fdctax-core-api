# SMS Integration Module

## Overview

This module provides SMS functionality for the FDC Tax Core application, enabling automated and manual SMS communications with clients.

**Current Status:** Phase 0 - Scaffolding Complete

## Module Structure

```
/app/backend/sms_integration/
├── __init__.py          # Module exports
├── sms_client.py        # Provider interface (Twilio, etc.)
├── sms_sender.py        # High-level sending service
├── webhook_handler.py   # Inbound SMS processing
├── schema.py            # Database models (placeholder)
└── README.md            # This file
```

## Phases

### Phase 0: Scaffolding (Current) ✅
- Module structure created
- Stub classes and methods
- Environment variable placeholders
- API endpoint stub (`/api/sms/send`)
- Documentation

### Phase 1: Provider Integration (Agent 4)
- Twilio SDK integration
- Outbound SMS sending
- Delivery status webhooks
- Rate limiting
- Audit logging

### Phase 2: Inbound SMS
- Webhook endpoint for receiving SMS
- Message parsing and storage
- Client matching (phone → CRM)
- Auto-reply functionality
- Database schema migration

### Phase 3: Automation
- Appointment reminders
- Document request notifications
- Payment reminders
- Tax deadline alerts
- Bulk messaging

## Environment Variables

Add these to `/app/backend/.env`:

```bash
# SMS Integration
SMS_PROVIDER=twilio              # Provider: twilio, messagebird, vonage
SMS_ACCOUNT_SID=                 # Twilio Account SID
SMS_AUTH_TOKEN=                  # Twilio Auth Token
SMS_FROM_NUMBER=                 # Default sender number (+61...)
SMS_WEBHOOK_SECRET=              # Webhook signature secret
```

## API Endpoints

### Current (Phase 0)

| Method | Endpoint | Description | Status |
|--------|----------|-------------|--------|
| POST | `/api/sms/send` | Send SMS | Stub (returns not_implemented) |

### Future (Phase 1+)

| Method | Endpoint | Description | Phase |
|--------|----------|-------------|-------|
| POST | `/api/sms/send` | Send SMS message | 1 |
| POST | `/api/sms/send-bulk` | Send bulk SMS | 1 |
| POST | `/api/sms/send-template` | Send from template | 1 |
| GET | `/api/sms/messages` | List messages | 2 |
| GET | `/api/sms/messages/{id}` | Get message details | 2 |
| POST | `/api/sms/webhook` | Receive inbound SMS | 2 |
| GET | `/api/sms/stats` | Get SMS statistics | 2 |
| GET | `/api/sms/templates` | List templates | 2 |
| POST | `/api/sms/templates` | Create template | 2 |

## Provider Options

### Twilio (Recommended)
- Most popular, well-documented
- Australian numbers available
- Delivery receipts
- Two-way messaging
- Pricing: ~$0.05-0.08 per SMS

### MessageBird
- European provider
- Competitive pricing
- Good API
- Pricing: ~$0.04-0.06 per SMS

### Vonage (Nexmo)
- Enterprise-grade
- Global coverage
- Advanced features
- Pricing: ~$0.05-0.07 per SMS

## Usage Examples

### Sending SMS (Phase 1)

```python
from sms_integration import SMSClient, SMSSender, SMSMessage, SMSMessageType

# Initialize client
client = SMSClient()
sender = SMSSender(client)

# Send simple message
message = SMSMessage(
    to="+61400123456",
    message="Hello from FDC Tax!",
    message_type=SMSMessageType.NOTIFICATION,
    client_id="client-001"
)
result = sender.send(message)

# Send from template
result = sender.send_from_template(
    to="+61400123456",
    template_id="appointment_reminder",
    variables={
        "client_name": "John",
        "date": "Monday 15th",
        "time": "2:00 PM"
    }
)
```

### Webhook Handling (Phase 2)

```python
from sms_integration import SMSWebhookHandler

handler = SMSWebhookHandler()

# In FastAPI endpoint
@router.post("/webhook")
async def receive_sms(request: Request):
    payload = await request.json()
    signature = request.headers.get("X-Twilio-Signature")
    
    if not handler.verify_signature(await request.body(), signature):
        raise HTTPException(status_code=401)
    
    sms = handler.parse_webhook(payload)
    result = handler.process_inbound(sms)
    
    return {"status": "received"}
```

## Database Schema (Phase 2)

```sql
-- sms_messages
CREATE TABLE sms_messages (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(100) UNIQUE,
    direction VARCHAR(20) NOT NULL,  -- inbound/outbound
    from_number VARCHAR(50) NOT NULL,
    to_number VARCHAR(50) NOT NULL,
    body TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'pending',
    provider VARCHAR(30) DEFAULT 'twilio',
    client_id VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## RBAC Permissions

| Role | Send SMS | View Messages | Manage Templates |
|------|----------|---------------|------------------|
| admin | ✅ | ✅ | ✅ |
| staff | ✅ | ✅ | ❌ |
| tax_agent | ✅ | ✅ (own clients) | ❌ |
| client | ❌ | ❌ | ❌ |

## Security Considerations

1. **Credentials**: Never commit SMS_AUTH_TOKEN to version control
2. **Webhooks**: Always validate webhook signatures
3. **Rate Limiting**: Implement per-recipient rate limits
4. **Audit Logging**: Log all SMS operations
5. **PII**: Phone numbers are PII - handle appropriately

## Testing

```bash
# Test stub endpoint
curl -X POST https://your-domain/api/sms/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "+61400123456", "message": "Test"}'

# Expected response (Phase 0)
{"status": "not_implemented"}
```

## Handoff Notes for Agent 4

1. **SMSClient.send_sms()**: Implement Twilio integration here
2. **Twilio SDK**: `pip install twilio`
3. **Phone Format**: Use E.164 format (+61400123456)
4. **Error Handling**: Twilio raises `TwilioRestException`
5. **Delivery Status**: Use Twilio status callbacks
6. **Testing**: Use Twilio test credentials for development

---

*Last Updated: December 31, 2025*
*Phase: 0 - Scaffolding*
