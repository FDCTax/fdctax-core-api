from .user import router as user_router
from .admin import router as admin_router
from .kb import router as kb_router
from .recurring import router as recurring_router
from .documents import router as documents_router
from .auth import router as auth_router
from .audit import router as audit_router
from .luna import router as luna_router
from .calendly import integrations_router, appointments_router
# Use PostgreSQL-backed workpaper router (replaces file-based router)
from .workpaper_db import router as workpaper_router
# Motor Vehicle module router
from .motor_vehicle import router as mv_router

__all__ = [
    'user_router', 
    'admin_router', 
    'kb_router', 
    'recurring_router', 
    'documents_router', 
    'auth_router', 
    'audit_router', 
    'luna_router',
    'integrations_router',
    'appointments_router',
    'workpaper_router',
    'mv_router',
]
