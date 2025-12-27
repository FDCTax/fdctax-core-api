from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

from database import get_db
from services.auth import (
    AuthService,
    LoginRequest,
    RegisterRequest,
    ChangePasswordRequest,
    Token,
    AuthUser,
    UserRole,
    seed_test_users
)
from middleware.auth import (
    get_current_user_required,
    get_current_user,
    RoleChecker,
    require_admin,
    require_staff
)
from services.audit import log_auth_action, log_action, AuditAction, ResourceType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


# Helper to extract request metadata for audit
def _get_request_metadata(request: Request) -> dict:
    """Extract IP address and user agent from request for audit logging"""
    ip_address = None
    user_agent = request.headers.get("user-agent", "")[:500] if request else None
    
    if request:
        # Check for forwarded headers
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            ip_address = forwarded.split(",")[0].strip()
        else:
            real_ip = request.headers.get("x-real-ip")
            if real_ip:
                ip_address = real_ip
            elif hasattr(request, 'client') and request.client:
                ip_address = request.client.host
    
    return {"ip_address": ip_address, "user_agent": user_agent}


# ==================== PUBLIC ENDPOINTS ====================

@router.post("/login", response_model=Token)
async def login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and return JWT tokens.
    
    Returns:
    - access_token: JWT for API access (expires in 1 hour)
    - refresh_token: JWT for refreshing access token (expires in 7 days)
    
    Example:
    ```json
    {
      "email": "admin@fdctax.com",
      "password": "admin123"
    }
    ```
    """
    auth_service = AuthService(db)
    token = await auth_service.login(login_data.email, login_data.password)
    
    if not token:
        # Log failed login attempt
        log_auth_action(
            action=AuditAction.USER_LOGIN_FAILED,
            user_email=login_data.email,
            details={"reason": "Invalid email or password"},
            request=request,
            success=False,
            error_message="Invalid credentials"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Log successful login
    log_auth_action(
        action=AuditAction.USER_LOGIN,
        user_id=token.user_id,
        user_email=token.email,
        details={"role": token.role},
        request=request
    )
    
    return token


@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str = Query(..., description="Refresh token from login"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Refresh access token using a valid refresh token.
    
    Use this when access token expires to get a new one without re-logging in.
    """
    auth_service = AuthService(db)
    token = await auth_service.refresh_tokens(refresh_token)
    
    if not token:
        log_auth_action(
            action=AuditAction.TOKEN_REFRESH,
            details={"reason": "Invalid or expired refresh token"},
            request=request,
            success=False,
            error_message="Invalid refresh token"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    # Log successful token refresh
    log_auth_action(
        action=AuditAction.TOKEN_REFRESH,
        user_id=token.user_id,
        user_email=token.email,
        request=request
    )
    
    return token


@router.post("/register", response_model=dict)
async def register(
    register_data: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user account.
    
    New users are assigned the 'client' role by default.
    Admin registration requires admin privileges.
    """
    # Prevent non-admins from creating admin/staff accounts
    if register_data.role in [UserRole.admin.value, UserRole.staff.value]:
        log_auth_action(
            action=AuditAction.USER_REGISTER,
            user_email=register_data.email,
            details={"attempted_role": register_data.role, "reason": "Forbidden role"},
            request=request,
            success=False,
            error_message="Cannot self-register as admin or staff"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot self-register as admin or staff"
        )
    
    auth_service = AuthService(db)
    
    try:
        user = await auth_service.register_user(
            email=register_data.email,
            password=register_data.password,
            first_name=register_data.first_name,
            last_name=register_data.last_name,
            role=register_data.role
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
        
        # Log successful registration
        log_auth_action(
            action=AuditAction.USER_REGISTER,
            user_id=user.id,
            user_email=user.email,
            details={
                "role": user.role,
                "first_name": register_data.first_name,
                "last_name": register_data.last_name
            },
            request=request
        )
        
        return {
            "success": True,
            "message": "Registration successful",
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user.role
            }
        }
        
    except ValueError as e:
        log_auth_action(
            action=AuditAction.USER_REGISTER,
            user_email=register_data.email,
            details={"error": str(e)},
            request=request,
            success=False,
            error_message=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ==================== AUTHENTICATED ENDPOINTS ====================

@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: AuthUser = Depends(get_current_user_required)
):
    """
    Get current authenticated user information.
    
    Requires valid access token in Authorization header.
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "role": current_user.role,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "is_active": current_user.is_active,
        "permissions": {
            "is_admin": current_user.is_admin(),
            "is_staff": current_user.is_staff(),
            "can_access_admin": current_user.is_staff(),
            "can_access_user": True
        }
    }


@router.post("/change-password")
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: AuthUser = Depends(get_current_user_required),
    db: AsyncSession = Depends(get_db)
):
    """
    Change current user's password.
    
    Requires current password for verification.
    """
    auth_service = AuthService(db)
    
    success = await auth_service.change_password(
        user_id=current_user.id,
        current_password=password_data.current_password,
        new_password=password_data.new_password
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )
    
    return {"success": True, "message": "Password changed successfully"}


@router.post("/logout")
async def logout(
    current_user: AuthUser = Depends(get_current_user_required)
):
    """
    Logout current user.
    
    Note: Since JWTs are stateless, this endpoint mainly serves as a
    client-side indicator. For true logout, client should discard the tokens.
    
    In production, consider implementing a token blacklist.
    """
    return {
        "success": True,
        "message": "Logged out successfully. Please discard your tokens."
    }


# ==================== ADMIN ENDPOINTS ====================

@router.post("/admin/register", response_model=dict)
async def admin_register_user(
    register_data: RegisterRequest,
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: Register a new user with any role.
    
    Only admins can create admin/staff accounts.
    """
    auth_service = AuthService(db)
    
    try:
        user = await auth_service.register_user(
            email=register_data.email,
            password=register_data.password,
            first_name=register_data.first_name,
            last_name=register_data.last_name,
            role=register_data.role
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
        
        return {
            "success": True,
            "message": f"User created with role: {user.role}",
            "user": {
                "id": user.id,
                "email": user.email,
                "role": user.role
            }
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.patch("/admin/users/{user_id}/role")
async def set_user_role(
    user_id: str,
    role: str = Query(..., description="New role (admin, staff, client)"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: Change a user's role.
    """
    if role not in [r.value for r in UserRole]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {[r.value for r in UserRole]}"
        )
    
    auth_service = AuthService(db)
    
    # Verify user exists
    user = await auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    auth_service.set_user_role(user_id, role)
    
    return {
        "success": True,
        "message": f"Role updated to: {role}",
        "user_id": user_id,
        "new_role": role
    }


@router.post("/admin/users/{user_id}/set-password")
async def admin_set_password(
    user_id: str,
    new_password: str = Query(..., description="New password", min_length=6),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: Set a user's password directly.
    
    Use with caution. Useful for password resets.
    """
    auth_service = AuthService(db)
    
    success = await auth_service.set_user_password(user_id, new_password)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return {"success": True, "message": "Password set successfully"}


@router.get("/admin/roles")
async def list_role_assignments(
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: List role assignments.
    """
    auth_service = AuthService(db)
    
    return {
        "admin_emails": auth_service.role_storage.list_admin_emails(),
        "staff_emails": auth_service.role_storage.list_staff_emails(),
        "available_roles": [r.value for r in UserRole]
    }


@router.post("/admin/roles/add-admin")
async def add_admin_email(
    email: str = Query(..., description="Email to add to admin list"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: Add an email to the admin role list.
    
    Users with this email will automatically be admins.
    """
    auth_service = AuthService(db)
    auth_service.role_storage.add_admin_email(email)
    
    return {"success": True, "message": f"Added {email} to admin list"}


@router.post("/admin/roles/add-staff")
async def add_staff_email(
    email: str = Query(..., description="Email to add to staff list"),
    current_user: AuthUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Admin: Add an email to the staff role list.
    """
    auth_service = AuthService(db)
    auth_service.role_storage.add_staff_email(email)
    
    return {"success": True, "message": f"Added {email} to staff list"}


# ==================== UTILITY ENDPOINTS ====================

@router.post("/seed-test-users")
async def seed_test_users_endpoint(
    admin_key: str = Query(..., description="Admin key for seeding"),
    db: AsyncSession = Depends(get_db)
):
    """
    Seed test users for development.
    
    Creates:
    - admin@fdctax.com (password: admin123, role: admin)
    - staff@fdctax.com (password: staff123, role: staff)
    - client@example.com (password: client123, role: client)
    
    Requires admin_key = "fdc-seed-2025" for security.
    """
    if admin_key != "fdc-seed-2025":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin key"
        )
    
    created = await seed_test_users(db)
    
    return {
        "success": True,
        "message": "Test users seeded",
        "created_users": created,
        "test_credentials": [
            {"email": "admin@fdctax.com", "password": "admin123", "role": "admin"},
            {"email": "staff@fdctax.com", "password": "staff123", "role": "staff"},
            {"email": "client@example.com", "password": "client123", "role": "client"}
        ]
    }


@router.get("/verify")
async def verify_token(
    current_user: AuthUser = Depends(get_current_user)
):
    """
    Verify if a token is valid.
    
    Returns user info if valid, null if invalid or no token.
    """
    if not current_user:
        return {"valid": False, "user": None}
    
    return {
        "valid": True,
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "role": current_user.role
        }
    }
