"""
Secret Authority Verification Endpoints

These endpoints are used by Secret Authority to verify:
- Email module readiness (RESEND_API_KEY)
- TFN encryption capability (ENCRYPTION_KEY)
- Internal authentication configuration (INTERNAL_API_KEY)

All endpoints are mounted at root level (not under /api) for Secret Authority access.
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from utils.encryption import (
    encrypt_tfn, 
    decrypt_tfn, 
    is_encryption_configured,
    EncryptionError,
    DecryptionError,
    KeyNotConfiguredError
)

logger = logging.getLogger(__name__)

# Create router without prefix - will be mounted at root
router = APIRouter(tags=["Secret Authority Verification"])


# ==================== REQUEST/RESPONSE MODELS ====================

class TFNEncryptRequest(BaseModel):
    """Request model for TFN encryption"""
    tfn: str = Field(..., description="TFN to encrypt (9 digits)")


class TFNEncryptResponse(BaseModel):
    """Response model for TFN encryption"""
    encrypted: str


class TFNDecryptRequest(BaseModel):
    """Request model for TFN decryption"""
    encrypted: str = Field(..., description="Encrypted TFN string")


class TFNDecryptResponse(BaseModel):
    """Response model for TFN decryption"""
    tfn: str


class EmailStatusResponse(BaseModel):
    """Response model for email status"""
    ready: bool


class InternalStatusResponse(BaseModel):
    """Response model for internal auth status"""
    internal_auth_configured: bool


class StatusResponse(BaseModel):
    """Response model for general status"""
    status: str
    encryption_configured: bool
    email_configured: bool
    internal_auth_configured: bool


# ==================== ENDPOINTS ====================

@router.get("/status", response_model=StatusResponse)
async def get_status():
    """
    General status endpoint for Secret Authority.
    
    Returns overall system readiness.
    """
    encryption_key = os.environ.get("ENCRYPTION_KEY")
    resend_key = os.environ.get("RESEND_API_KEY") or os.environ.get("EMAIL_API_KEY")
    internal_key = os.environ.get("INTERNAL_API_KEY")
    
    return StatusResponse(
        status="ok",
        encryption_configured=bool(encryption_key) and is_encryption_configured(),
        email_configured=bool(resend_key),
        internal_auth_configured=bool(internal_key)
    )


@router.get("/email/status", response_model=EmailStatusResponse)
async def get_email_status():
    """
    Verify email module readiness.
    
    Checks for presence of RESEND_API_KEY or EMAIL_API_KEY.
    
    Returns:
        {"ready": true} if configured
        {"ready": false} if not configured
    """
    # Check for either RESEND_API_KEY or EMAIL_API_KEY
    resend_key = os.environ.get("RESEND_API_KEY")
    email_key = os.environ.get("EMAIL_API_KEY")
    
    is_ready = bool(resend_key or email_key)
    
    logger.info(f"Email status check: ready={is_ready}")
    
    return EmailStatusResponse(ready=is_ready)


@router.post("/tfn/encrypt", response_model=TFNEncryptResponse)
async def encrypt_tfn_endpoint(request: TFNEncryptRequest):
    """
    Encrypt TFN using ENCRYPTION_KEY.
    
    Input: {"tfn": "123456782"}
    Output: {"encrypted": "<string>"}
    
    Requires ENCRYPTION_KEY to be configured.
    """
    if not is_encryption_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Encryption not configured. ENCRYPTION_KEY environment variable is required."
        )
    
    try:
        encrypted = encrypt_tfn(request.tfn)
        
        if not encrypted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Encryption failed - no result returned"
            )
        
        logger.info("TFN encrypted successfully")
        
        return TFNEncryptResponse(encrypted=encrypted)
        
    except EncryptionError as e:
        logger.error(f"TFN encryption failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/tfn/decrypt", response_model=TFNDecryptResponse)
async def decrypt_tfn_endpoint(request: TFNDecryptRequest):
    """
    Decrypt TFN using ENCRYPTION_KEY.
    
    Input: {"encrypted": "<string>"}
    Output: {"tfn": "123456782"}
    
    Requires ENCRYPTION_KEY to be configured.
    """
    if not is_encryption_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Encryption not configured. ENCRYPTION_KEY environment variable is required."
        )
    
    try:
        decrypted = decrypt_tfn(request.encrypted)
        
        if not decrypted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Decryption failed - no result returned"
            )
        
        logger.info("TFN decrypted successfully")
        
        return TFNDecryptResponse(tfn=decrypted)
        
    except KeyNotConfiguredError as e:
        logger.error(f"TFN decryption failed - key not configured: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Encryption key not configured"
        )
    except DecryptionError as e:
        logger.error(f"TFN decryption failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/internal/status", response_model=InternalStatusResponse)
async def get_internal_status():
    """
    Confirm internal auth is configured.
    
    Checks for presence of INTERNAL_API_KEY.
    
    Returns:
        {"internal_auth_configured": true} if configured
        {"internal_auth_configured": false} if not configured
    """
    internal_key = os.environ.get("INTERNAL_API_KEY")
    
    is_configured = bool(internal_key)
    
    logger.info(f"Internal auth status check: configured={is_configured}")
    
    return InternalStatusResponse(internal_auth_configured=is_configured)
