"""
SMS Client - Twilio Provider Implementation

This module provides real SMS sending via Twilio.

Usage:
    client = SMSClient()
    result = await client.send_sms(to='+61400123456', message='Hello!')
"""

import os
import re
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)


@dataclass
class SMSResult:
    """Result of an SMS operation"""
    success: bool
    message_id: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[int] = None
    provider_response: Optional[Dict[str, Any]] = None
    sent_at: Optional[datetime] = None


class SMSClient:
    """
    SMS Client - Twilio integration for sending SMS messages.
    
    Environment Variables:
        SMS_ACCOUNT_SID: Twilio Account SID
        SMS_AUTH_TOKEN: Twilio Auth Token
        SMS_FROM_NUMBER: Twilio Phone Number (sender)
        SMS_PROVIDER: Provider name (default: twilio)
    
    Usage:
        client = SMSClient()
        if client.is_configured():
            result = await client.send_sms('+61400123456', 'Hello!')
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
            account_sid: Twilio Account SID (or SMS_ACCOUNT_SID env var)
            auth_token: Twilio Auth Token (or SMS_AUTH_TOKEN env var)
            from_number: Sender phone number (or SMS_FROM_NUMBER env var)
            provider: Provider name (only 'twilio' supported currently)
        """
        self.account_sid = account_sid or os.environ.get('SMS_ACCOUNT_SID', '')
        self.auth_token = auth_token or os.environ.get('SMS_AUTH_TOKEN', '')
        self.from_number = from_number or os.environ.get('SMS_FROM_NUMBER', '')
        self.provider = provider or os.environ.get('SMS_PROVIDER', 'twilio')
        
        self._client: Optional[TwilioClient] = None
        self._initialized = False
    
    def is_configured(self) -> bool:
        """Check if SMS client is properly configured."""
        return bool(self.account_sid and self.auth_token and self.from_number)
    
    def _ensure_initialized(self) -> bool:
        """Ensure Twilio client is initialized."""
        if self._initialized and self._client:
            return True
        
        if not self.is_configured():
            logger.warning("SMS client not configured - missing credentials")
            return False
        
        try:
            self._client = TwilioClient(self.account_sid, self.auth_token)
            self._initialized = True
            logger.info(f"SMS client initialized (provider: {self.provider})")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Twilio client: {e}")
            return False
    
    async def send_sms(
        self,
        to: str,
        message: str,
        from_number: Optional[str] = None
    ) -> SMSResult:
        """
        Send an SMS message via Twilio.
        
        Args:
            to: Recipient phone number (E.164 format preferred)
            message: Message content (max 1600 chars)
            from_number: Override sender number (optional)
            
        Returns:
            SMSResult: Result of the send operation
        """
        if not self._ensure_initialized():
            return SMSResult(
                success=False,
                error="SMS client not configured. Check environment variables.",
                error_code=500
            )
        
        # Normalize phone number
        normalized_to = self.normalize_phone_number(to)
        sender = from_number or self.from_number
        
        # Validate
        if not self.validate_phone_number(normalized_to):
            return SMSResult(
                success=False,
                error=f"Invalid phone number format: {to}",
                error_code=400
            )
        
        if len(message) > 1600:
            return SMSResult(
                success=False,
                error="Message exceeds 1600 character limit",
                error_code=400
            )
        
        if not message.strip():
            return SMSResult(
                success=False,
                error="Message cannot be empty",
                error_code=400
            )
        
        try:
            logger.info(f"Sending SMS to {normalized_to[:6]}***")
            
            # Send via Twilio (sync call - Twilio SDK is synchronous)
            twilio_message = self._client.messages.create(
                body=message,
                from_=sender,
                to=normalized_to
            )
            
            logger.info(f"SMS sent successfully: {twilio_message.sid}")
            
            return SMSResult(
                success=True,
                message_id=twilio_message.sid,
                status=twilio_message.status,
                sent_at=datetime.now(timezone.utc),
                provider_response={
                    "sid": twilio_message.sid,
                    "status": twilio_message.status,
                    "date_created": str(twilio_message.date_created),
                    "direction": twilio_message.direction,
                    "num_segments": twilio_message.num_segments,
                    "price": twilio_message.price,
                    "price_unit": twilio_message.price_unit,
                    "error_code": twilio_message.error_code,
                    "error_message": twilio_message.error_message
                }
            )
            
        except TwilioRestException as e:
            logger.error(f"Twilio API error: {e.code} - {e.msg}")
            return SMSResult(
                success=False,
                error=e.msg,
                error_code=e.code,
                provider_response={
                    "code": e.code,
                    "message": e.msg,
                    "status": e.status
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error sending SMS: {e}")
            return SMSResult(
                success=False,
                error=str(e),
                error_code=500
            )
    
    async def get_message_status(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the status of a sent message.
        
        Args:
            message_id: Twilio message SID
            
        Returns:
            Message status dict or None if not found
        """
        if not self._ensure_initialized():
            return None
        
        try:
            message = self._client.messages(message_id).fetch()
            return {
                "message_id": message.sid,
                "status": message.status,
                "to": message.to,
                "from": message.from_,
                "body": message.body[:50] + "..." if len(message.body) > 50 else message.body,
                "date_created": str(message.date_created),
                "date_sent": str(message.date_sent) if message.date_sent else None,
                "date_updated": str(message.date_updated) if message.date_updated else None,
                "error_code": message.error_code,
                "error_message": message.error_message,
                "num_segments": message.num_segments,
                "price": message.price,
                "price_unit": message.price_unit
            }
        except TwilioRestException as e:
            logger.error(f"Failed to get message status: {e.msg}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting message status: {e}")
            return None
    
    def validate_phone_number(self, phone: str) -> bool:
        """
        Validate a phone number format (E.164).
        
        Args:
            phone: Phone number to validate
            
        Returns:
            bool: True if valid format
        """
        # E.164 format: + followed by 7-15 digits
        pattern = r'^\+[1-9]\d{6,14}$'
        cleaned = re.sub(r'[\s\-\(\)]', '', phone)
        return bool(re.match(pattern, cleaned))
    
    def normalize_phone_number(self, phone: str, country_code: str = '+61') -> str:
        """
        Normalize phone number to E.164 format.
        
        Args:
            phone: Phone number to normalize
            country_code: Default country code (Australia +61)
            
        Returns:
            Normalized phone number in E.164 format
        """
        # Remove all non-digit characters except +
        cleaned = re.sub(r'[^\d+]', '', phone)
        
        # Already in E.164 format
        if cleaned.startswith('+'):
            return cleaned
        
        # Australian formats
        if cleaned.startswith('61') and len(cleaned) >= 11:
            return '+' + cleaned
        
        # Australian mobile starting with 04
        if cleaned.startswith('04') and len(cleaned) == 10:
            return '+61' + cleaned[1:]
        
        # Other Australian numbers starting with 0
        if cleaned.startswith('0') and len(cleaned) == 10:
            return '+61' + cleaned[1:]
        
        # Assume local number needs country code
        return country_code + cleaned
    
    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Get Twilio account information for diagnostics."""
        if not self._ensure_initialized():
            return None
        
        try:
            account = self._client.api.accounts(self.account_sid).fetch()
            return {
                "sid": account.sid,
                "friendly_name": account.friendly_name,
                "status": account.status,
                "type": account.type
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return None
