"""
Internal Service Authentication Middleware

Provides API key-based authentication for service-to-service communication.
Used for internal microservice calls that don't go through user JWT auth.

Environment Variables:
    INTERNAL_API_KEY: Primary API key for internal services
    INTERNAL_API_KEYS: Comma-separated list of valid keys (for key rotation)

Usage:
    from middleware.internal_auth import require_internal_service, validate_internal_key
    
    @router.post("/internal/sync")
    async def internal_sync(
        data: SyncRequest,
        service: InternalService = Depends(require_internal_service)
    ):
        # service.name contains the authenticated service name
        pass

Headers:
    X-Internal-Api-Key: <api_key>
    X-Service-Name: <service_name> (optional, for logging)
"""

import os
import secrets
import logging
from typing import Optional, List, Set
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

# Header names
API_KEY_HEADER = "X-Internal-Api-Key"
SERVICE_NAME_HEADER = "X-Service-Name"

# Environment variable names
INTERNAL_API_KEY_ENV = "INTERNAL_API_KEY"
INTERNAL_API_KEYS_ENV = "INTERNAL_API_KEYS"  # Comma-separated for rotation


@dataclass
class InternalService:
    """Represents an authenticated internal service"""
    name: str
    api_key_hash: str  # Last 8 chars of key for logging
    is_authenticated: bool = True


class InternalAuthError(Exception):
    """Base exception for internal auth errors"""
    pass


class InvalidApiKeyError(InternalAuthError):
    """Raised when API key is invalid"""
    pass


class MissingApiKeyError(InternalAuthError):
    """Raised when API key is missing"""
    pass


@lru_cache(maxsize=1)
def _get_valid_api_keys() -> Set[str]:
    """
    Get set of valid API keys from environment.
    Cached for performance.
    
    Returns:
        Set of valid API key strings
    """
    keys = set()
    
    # Primary key
    primary_key = os.environ.get(INTERNAL_API_KEY_ENV)
    if primary_key:
        keys.add(primary_key.strip())
    
    # Additional keys (for rotation)
    additional_keys = os.environ.get(INTERNAL_API_KEYS_ENV, "")
    if additional_keys:
        for key in additional_keys.split(","):
            key = key.strip()
            if key:
                keys.add(key)
    
    if not keys:
        logger.warning("No internal API keys configured - internal auth disabled")
    
    return keys


def is_internal_auth_configured() -> bool:
    """Check if internal authentication is configured."""
    return len(_get_valid_api_keys()) > 0


def validate_internal_key(api_key: str) -> bool:
    """
    Validate an internal API key.
    
    Args:
        api_key: The API key to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not api_key:
        return False
    
    valid_keys = _get_valid_api_keys()
    
    if not valid_keys:
        logger.warning("No valid API keys configured")
        return False
    
    # Constant-time comparison to prevent timing attacks
    for valid_key in valid_keys:
        if secrets.compare_digest(api_key, valid_key):
            return True
    
    return False


def generate_internal_api_key(length: int = 48) -> str:
    """
    Generate a new internal API key.
    
    Args:
        length: Length of the key (default 48 chars)
        
    Returns:
        Secure random API key string
    """
    return secrets.token_urlsafe(length)


# FastAPI dependency for API key header
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


async def get_internal_service(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header)
) -> InternalService:
    """
    FastAPI dependency to authenticate internal service requests.
    
    Args:
        request: The incoming request
        api_key: API key from header
        
    Returns:
        InternalService object with service info
        
    Raises:
        HTTPException: If authentication fails
    """
    # Get service name from header (optional)
    service_name = request.headers.get(SERVICE_NAME_HEADER, "unknown")
    
    # Check if API key provided
    if not api_key:
        logger.warning(f"Missing API key from service: {service_name}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing internal API key",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    # Validate API key
    if not validate_internal_key(api_key):
        logger.warning(f"Invalid API key from service: {service_name}, key ending: ...{api_key[-8:]}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal API key",
            headers={"WWW-Authenticate": "ApiKey"}
        )
    
    logger.info(f"Internal service authenticated: {service_name}")
    
    return InternalService(
        name=service_name,
        api_key_hash=f"...{api_key[-8:]}"
    )


# Convenience alias - use directly as dependency
# Example: service: InternalService = Depends(get_internal_service)
require_internal_service = get_internal_service


async def optional_internal_service(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header)
) -> Optional[InternalService]:
    """
    Optional internal service authentication.
    Returns None instead of raising exception if not authenticated.
    """
    if not api_key:
        return None
    
    if not validate_internal_key(api_key):
        return None
    
    service_name = request.headers.get(SERVICE_NAME_HEADER, "unknown")
    
    return InternalService(
        name=service_name,
        api_key_hash=f"...{api_key[-8:]}"
    )


class InternalOrUserAuth:
    """
    Dependency that accepts either internal API key OR user JWT.
    Useful for endpoints that can be called by both services and users.
    """
    
    def __init__(self, allowed_roles: Optional[List[str]] = None):
        """
        Args:
            allowed_roles: List of user roles allowed (if using JWT)
        """
        self.allowed_roles = allowed_roles or []
    
    async def __call__(
        self,
        request: Request,
        api_key: Optional[str] = Depends(api_key_header)
    ) -> dict:
        """
        Authenticate via internal API key or user JWT.
        
        Returns:
            Dict with auth_type ('internal' or 'user') and identity info
        """
        # Try internal API key first
        if api_key and validate_internal_key(api_key):
            service_name = request.headers.get(SERVICE_NAME_HEADER, "unknown")
            return {
                "auth_type": "internal",
                "service_name": service_name,
                "api_key_hash": f"...{api_key[-8:]}"
            }
        
        # Fall back to JWT auth
        from middleware.auth import get_current_user
        
        try:
            user = await get_current_user(request)
            
            # Check role if specified
            if self.allowed_roles and user.role not in self.allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied. Required roles: {self.allowed_roles}"
                )
            
            return {
                "auth_type": "user",
                "user_id": user.id,
                "email": user.email,
                "role": user.role
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Auth failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required (internal API key or user token)"
            )


# Pre-configured instances
require_internal_or_admin = InternalOrUserAuth(allowed_roles=["admin"])
require_internal_or_staff = InternalOrUserAuth(allowed_roles=["admin", "staff"])
