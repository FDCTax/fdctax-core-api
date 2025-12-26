# FDC Tax Core + CRM Sync

Backend API for FDC Tax CRM sync, user onboarding state, and Meet Oscar wizard integration.

## Project Structure

```
/app
├── backend/
│   ├── server.py           # FastAPI main application
│   ├── requirements.txt    # Python dependencies
│   ├── database/           # PostgreSQL connection
│   ├── models/             # Pydantic schemas
│   ├── routers/            # API route handlers
│   ├── services/           # Business logic (CRM sync, White-glove)
│   └── README.md           # API documentation
├── frontend/               # React frontend (MyFDC)
└── tests/                  # Test files
```

## Features

- **User Onboarding State**: Track and update wizard progress flags
- **Meet Oscar Wizard**: Enable/disable enhanced OCR preprocessing
- **Task Management**: CRM task assignment and sync to educator dashboards
- **Knowledge Base**: Luna AI response data from `luna_knowledge_base`
- **White-Glove Services**: Admin profile overrides, escalations, bulk tasks
- **CRM Sync**: Internal CRM → MyFDC frontend data synchronization

## Quick Start

```bash
# Backend
cd /app/backend
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# API Documentation
open http://localhost:8001/docs
```

## Key API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/user/tasks` | GET | Fetch tasks for a user |
| `/api/user/profile` | GET/POST | User profile + setup state |
| `/api/user/oscar` | POST | Toggle Oscar preprocessing |
| `/api/user/onboarding` | PATCH | Update onboarding flags |
| `/api/admin/users` | GET | List all users |
| `/api/admin/tasks` | GET/POST | Task management |
| `/api/admin/escalate` | POST | Luna escalation trigger |
| `/api/admin/sync/tasks` | POST | CRM task sync |
| `/api/kb/search` | GET | Knowledge base search |

## Database

Connected to FDC Tax PostgreSQL sandbox:
- Schema `myfdc`: users, user_tasks, user_settings, luna_knowledge_base
- Schema `crm`: tasks, messages

## Related Projects

- **MyFDC Frontend** (EMT-663f69)
- **FDC Tax + Knowledge Base** (EMT-385e5d)
