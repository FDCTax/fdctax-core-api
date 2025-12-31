"""
SMS Integration Module

Provides SMS sending functionality via Twilio.

Usage:
    from sms_integration import SMSClient, SMSSender, SMSMessage
    
    # Direct client usage
    client = SMSClient()
    result = await client.send_sms('+61400123456', 'Hello!')
    
    # High-level sender with templates
    sender = SMSSender()
    result = await sender.send_from_template(
        to='+61400123456',
        template_id='appointment_reminder',
        variables={'client_name': 'John', 'date': '2024-01-15', 'time': '10:00 AM'}
    )

Environment Variables:
    SMS_ACCOUNT_SID: Twilio Account SID
    SMS_AUTH_TOKEN: Twilio Auth Token
    SMS_FROM_NUMBER: Twilio Phone Number (sender)
    SMS_PROVIDER: Provider name (default: twilio)
    SMS_TEST_NUMBER: Test recipient number (optional)
"""

from .sms_client import SMSClient, SMSResult
from .sms_sender import SMSSender, SMSMessage, SMSMessageType, SendResult, DEFAULT_TEMPLATES

__all__ = [
    'SMSClient',
    'SMSResult',
    'SMSSender',
    'SMSMessage',
    'SMSMessageType',
    'SendResult',
    'DEFAULT_TEMPLATES',
]
