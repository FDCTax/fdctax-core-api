"""
Authentication Middleware and Dependencies

Provides:
- get_current_user: Extract and validate user from JWT token
- requires_role: Decorator for role-based access control
- RoleChecker: Dependency for role validation
"""

from functools import wraps
from typing import Optional, List, Callable
import logging

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.auth import (
    decode_token,
    AuthUser,
    AuthService,
    AuthRoleStorage,
    UserRole
)

logger = logging.getLogger(__name__)

# Security scheme
security = HTTPBearer(auto_error=False)


# ==================== DEPENDENCIES ====================

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[AuthUser]:
    """
    Extract current user from JWT token.
    Returns None if no token or invalid token.
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    token_data = decode_token(token)
    
    if not token_data:
        return None
    
    if token_data.token_type != "access":
        return None
    
    # Get role from storage (in case it changed)
    role_storage = AuthRoleStorage()
    role = role_storage.get_user_role(token_data.user_id, token_data.email)
    
    return AuthUser(
        id=token_data.user_id,
        email=token_data.email,
        role=role
    )


async def get_current_user_required(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> AuthUser:
    """
    Extract current user from JWT token.
    Raises 401 if no token or invalid token.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    token = credentials.credentials
    token_data = decode_token(token)
    
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    if token_data.token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Get role from storage
    role_storage = AuthRoleStorage()
    role = role_storage.get_user_role(token_data.user_id, token_data.email)
    
    return AuthUser(
        id=token_data.user_id,
        email=token_data.email,
        role=role
    )


class RoleChecker:
    """
    Dependency class for role-based access control.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user: AuthUser = Depends(RoleChecker(["admin"]))):
            ...
    """
    
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles
    
    async def __call__(
        self,
        credentials: HTTPAuthorizationCredentials = Depends(security),
        db: AsyncSession = Depends(get_db)
    ) -> AuthUser:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        token = credentials.credentials
        token_data = decode_token(token)
        
        if not token_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        if token_data.token_type != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type"
            )
        
        # Get current role
        role_storage = AuthRoleStorage()
        role = role_storage.get_user_role(token_data.user_id, token_data.email)
        
        if role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required roles: {self.allowed_roles}"
            )
        
        return AuthUser(
            id=token_data.user_id,
            email=token_data.email,
            role=role
        )


# Convenience role checkers
require_admin = RoleChecker([UserRole.admin.value])
require_staff = RoleChecker([UserRole.admin.value, UserRole.staff.value])
require_client = RoleChecker([UserRole.client.value])
require_any_authenticated = RoleChecker([UserRole.admin.value, UserRole.staff.value, UserRole.client.value])

# ==================== TRANSACTION ENGINE RBAC ====================
# Role checkers following the RBAC permissions matrix for Transaction Engine

# Bookkeeper Tab - Read access: staff, tax_agent, admin
require_bookkeeper_read = RoleChecker([UserRole.admin.value, UserRole.staff.value, UserRole.tax_agent.value])

# Bookkeeper Tab - Write access: staff, admin (no tax_agent, no client)
require_bookkeeper_write = RoleChecker([UserRole.admin.value, UserRole.staff.value])

# Workpaper Lock - Only tax_agent and admin can lock for workpapers
require_workpaper_lock = RoleChecker([UserRole.admin.value, UserRole.tax_agent.value])

# MyFDC Sync - Only client and admin can create via MyFDC
require_myfdc_sync = RoleChecker([UserRole.admin.value, UserRole.client.value])

# Import (Bank/OCR) - Only staff and admin can import
require_import = RoleChecker([UserRole.admin.value, UserRole.staff.value])


# ==================== DECORATOR ====================

def requires_role(allowed_roles: List[str]):
    """
    Decorator for role-based access control.
    
    Usage:
        @router.get("/admin-only")
        @requires_role(["admin"])
        async def admin_endpoint(...):
            ...
    
    Note: This decorator adds a dependency, so you need to include
    `current_user: AuthUser = Depends(get_current_user_required)` in your function.
    
    For cleaner usage, prefer the RoleChecker class as a dependency.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get current user from kwargs
            current_user = kwargs.get('current_user')
            
            if not current_user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated"
                )
            
            if current_user.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required roles: {allowed_roles}"
                )
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== OPTIONAL AUTH ====================

async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[AuthUser]:
    """
    Get current user if token provided, otherwise return None.
    Useful for endpoints that work differently for authenticated vs anonymous users.
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    token_data = decode_token(token)
    
    if not token_data or token_data.token_type != "access":
        return None
    
    role_storage = AuthRoleStorage()
    role = role_storage.get_user_role(token_data.user_id, token_data.email)
    
    return AuthUser(
        id=token_data.user_id,
        email=token_data.email,
        role=role
    )
