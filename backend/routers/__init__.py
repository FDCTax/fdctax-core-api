from .user import router as user_router
from .admin import router as admin_router
from .kb import router as kb_router

__all__ = ['user_router', 'admin_router', 'kb_router']
