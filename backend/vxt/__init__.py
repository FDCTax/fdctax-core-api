"""
VXT Phone System Integration Module

Provides phone call integration with VXT:
- Webhook processing for call events
- Call/transcript/recording management
- Client matching
- Workpaper auto-creation
"""

from .models import (
    VXTCallDB, VXTTranscriptDB, VXTRecordingDB,
    WorkpaperCallLinkDB, VXTWebhookLogDB
)
from .service import VXTWebhookService, VXTCallService, normalize_phone_number

__all__ = [
    "VXTCallDB",
    "VXTTranscriptDB",
    "VXTRecordingDB",
    "WorkpaperCallLinkDB",
    "VXTWebhookLogDB",
    "VXTWebhookService",
    "VXTCallService",
    "normalize_phone_number",
]
