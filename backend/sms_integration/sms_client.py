"""
SMS Client - Provider Interface

This module provides a unified interface for SMS provider integration.
Currently a stub - will be implemented in Phase 1 by Agent 4.

Supported Providers (Future):
- Twilio (default)
- MessageBird
- Vonage/Nexmo

Usage:
    client = SMSClient(
        account_sid=os.environ.get('SMS_ACCOUNT_SID'),
        auth_token=os.environ.get('SMS_AUTH_TOKEN')
    )
    client.send_sms(to='+61400123456', message='Hello!')
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SMSResult:
    """Result of an SMS operation"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    provider_response: Optional[Dict[str, Any]] = None


class SMSClient:
    """
    SMS Client - Interface for SMS provider operations.
    
    This is a stub class for Phase 0 scaffolding.
    Real provider integration will be added in Phase 1.
    
    Attributes:
        account_sid: Provider account SID/ID
        auth_token: Provider authentication token
        from_number: Default sender phone number
        provider: SMS provider name (twilio, messagebird, etc.)
    """
    
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        provider: str = "twilio"
    ):
        """
        Initialize SMS client.
        
        Args:
            account_sid: Provider account SID (from SMS_ACCOUNT_SID env var)
            auth_token: Provider auth token (from SMS_AUTH_TOKEN env var)
            from_number: Default sender number (from SMS_FROM_NUMBER env var)
            provider: SMS provider name (from SMS_PROVIDER env var)
        """
        self.account_sid = account_sid or os.environ.get('SMS_ACCOUNT_SID', '')
        self.auth_token = auth_token or os.environ.get('SMS_AUTH_TOKEN', '')
        self.from_number = from_number or os.environ.get('SMS_FROM_NUMBER', '')
        self.provider = provider or os.environ.get('SMS_PROVIDER', 'twilio')
        
        self._initialized = False
        self._client = None
    
    def is_configured(self) -> bool:
        """Check if SMS client is properly configured."""
        return bool(self.account_sid and self.auth_token and self.from_number)
    
    def initialize(self) -> bool:
        """
        Initialize the provider client.
        
        Returns:
            bool: True if initialization successful
            
        Note: Stub implementation - will be replaced in Phase 1.
        """
        if not self.is_configured():
            logger.warning("SMS client not configured - missing credentials")
            return False
        
        # TODO: Phase 1 - Initialize actual provider client
        # if self.provider == 'twilio':
        #     from twilio.rest import Client
        #     self._client = Client(self.account_sid, self.auth_token)
        
        logger.info(f"SMS client stub initialized (provider: {self.provider})")
        self._initialized = True
        return True
    
    def send_sms(self, to: str, message: str, from_number: Optional[str] = None) -> SMSResult:
        """
        Send an SMS message.
        
        Args:
            to: Recipient phone number (E.164 format preferred)
            message: Message content (max 1600 chars for Twilio)
            from_number: Override sender number (optional)
            
        Returns:
            SMSResult: Result of the send operation
            
        Raises:
            NotImplementedError: SMS sending not implemented yet (Phase 0)
        """
        raise NotImplementedError(
            "SMS sending not implemented yet. "
            "This is Phase 0 scaffolding - Phase 1 will add provider integration."
        )
    
    def get_message_status(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a sent message.
        
        Args:
            message_id: Provider message ID
            
        Returns:
            Message status dict or None
            
        Raises:
            NotImplementedError: Status check not implemented yet (Phase 0)
        """
        raise NotImplementedError(
            "Message status check not implemented yet. "
            "This is Phase 0 scaffolding."
        )
    
    def validate_phone_number(self, phone: str) -> bool:
        """
        Validate a phone number format.
        
        Args:
            phone: Phone number to validate
            
        Returns:
            bool: True if valid format
        """
        # Basic validation - E.164 format
        import re
        pattern = r'^\+?[1-9]\d{6,14}$'
        cleaned = re.sub(r'[\s\-\(\)]', '', phone)
        return bool(re.match(pattern, cleaned))
    
    def normalize_phone_number(self, phone: str, country_code: str = '+61') -> str:
        """
        Normalize phone number to E.164 format.
        
        Args:
            phone: Phone number to normalize
            country_code: Default country code (Australia +61)
            
        Returns:
            Normalized phone number
        """
        import re
        
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Handle Australian numbers
        if cleaned.startswith('+'):
            return cleaned
        elif cleaned.startswith('61') and len(cleaned) >= 11:
            return '+' + cleaned
        elif cleaned.startswith('04') and len(cleaned) == 10:
            return '+61' + cleaned[1:]
        elif cleaned.startswith('0') and len(cleaned) == 10:
            return '+61' + cleaned[1:]
        
        return country_code + cleaned
