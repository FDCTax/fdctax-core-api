"""
Secret Authority Client (A3-OCR-01)

Handles secure key retrieval from Secret Authority for OCR service.
Uses the provided contract:
- SECRET_AUTHORITY_URL=https://secure-keys-13.preview.emergentagent.com
- POST /api/v1/ocr/key with x-internal-service and x-internal-token headers
"""

import os
import logging
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OCRKeyCache:
    """Cache for OCR API key to avoid repeated requests."""
    key_material: str
    expires_at: datetime
    provider: str


class SecretAuthorityClient:
    """
    Client for Secret Authority service.
    
    Retrieves OCR API keys securely from the Secret Authority.
    Implements caching to minimize key requests.
    """
    
    # Cache TTL - keys are cached for 55 minutes (assuming 1 hour expiry)
    CACHE_TTL_MINUTES = 55
    
    def __init__(self):
        self.base_url = os.environ.get(
            'SECRET_AUTHORITY_URL',
            'https://secure-keys-13.preview.emergentagent.com'
        )
        self.internal_service = os.environ.get('OCR_INTERNAL_SERVICE', 'core')
        self.internal_token = os.environ.get('OCR_INTERNAL_TOKEN', '')
        
        # Key cache
        self._key_cache: Optional[OCRKeyCache] = None
        
        logger.info(f"SecretAuthorityClient initialized with URL: {self.base_url}")
    
    async def get_ocr_key(self) -> Optional[str]:
        """
        Get OCR API key from Secret Authority.
        
        Returns cached key if still valid, otherwise requests new key.
        
        Returns:
            API key string or None if retrieval failed
        """
        # Check cache first
        if self._is_cache_valid():
            logger.debug("Using cached OCR key")
            return self._key_cache.key_material
        
        # Request new key
        try:
            key_data = await self._request_ocr_key()
            if key_data and 'key_material' in key_data:
                # Cache the key
                self._key_cache = OCRKeyCache(
                    key_material=key_data['key_material'],
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=self.CACHE_TTL_MINUTES),
                    provider=key_data.get('provider', 'openai')
                )
                logger.info("Successfully retrieved and cached OCR key from Secret Authority")
                return self._key_cache.key_material
            else:
                logger.error(f"Invalid key response from Secret Authority: {key_data}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to get OCR key from Secret Authority: {e}")
            return None
    
    async def _request_ocr_key(self) -> Optional[Dict[str, Any]]:
        """
        Request OCR key from Secret Authority.
        
        POST /api/v1/ocr/key
        Headers:
            x-internal-service: core
            x-internal-token: <provided_by_agent5>
        """
        url = f"{self.base_url}/api/v1/ocr/key"
        
        headers = {
            "Content-Type": "application/json",
            "x-internal-service": self.internal_service,
        }
        
        # Add token if configured
        if self.internal_token:
            headers["x-internal-token"] = self.internal_token
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json={})
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(
                        f"Secret Authority returned {response.status_code}: {response.text}"
                    )
                    return None
                    
        except httpx.TimeoutException:
            logger.error("Secret Authority request timed out")
            return None
        except httpx.RequestError as e:
            logger.error(f"Secret Authority request error: {e}")
            return None
    
    def _is_cache_valid(self) -> bool:
        """Check if cached key is still valid."""
        if not self._key_cache:
            return False
        
        return datetime.now(timezone.utc) < self._key_cache.expires_at
    
    def get_cached_provider(self) -> Optional[str]:
        """Get the provider from cached key data."""
        if self._key_cache:
            return self._key_cache.provider
        return None
    
    def invalidate_cache(self):
        """Invalidate the key cache (e.g., on auth error)."""
        self._key_cache = None
        logger.info("OCR key cache invalidated")


# Global client instance
secret_authority_client = SecretAuthorityClient()
