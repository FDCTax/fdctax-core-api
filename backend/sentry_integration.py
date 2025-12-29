"""
FDC Core - Sentry Integration

Error tracking and performance monitoring with Sentry.
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Sentry SDK (optional dependency)
try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    SENTRY_AVAILABLE = True
except ImportError:
    SENTRY_AVAILABLE = False
    logger.warning("Sentry SDK not installed. Error tracking disabled.")


def init_sentry(
    dsn: Optional[str] = None,
    environment: str = "development",
    release: Optional[str] = None,
    sample_rate: float = 1.0,
    traces_sample_rate: float = 0.1,
) -> bool:
    """
    Initialize Sentry error tracking.
    
    Args:
        dsn: Sentry DSN (from environment if not provided)
        environment: Environment name (production, staging, development)
        release: Release version
        sample_rate: Error sampling rate (0.0 to 1.0)
        traces_sample_rate: Performance tracing sample rate
    
    Returns:
        True if Sentry was initialized, False otherwise
    """
    if not SENTRY_AVAILABLE:
        logger.info("Sentry SDK not available")
        return False
    
    dsn = dsn or os.environ.get("SENTRY_DSN", "")
    
    if not dsn:
        logger.info("Sentry DSN not configured. Error tracking disabled.")
        return False
    
    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            release=release or os.environ.get("GIT_SHA", "unknown"),
            sample_rate=sample_rate,
            traces_sample_rate=traces_sample_rate,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
                LoggingIntegration(
                    level=logging.INFO,
                    event_level=logging.ERROR
                ),
            ],
            # Don't send PII
            send_default_pii=False,
            # Filter sensitive data
            before_send=filter_sensitive_data,
            # Ignore common noise
            ignore_errors=[
                "ConnectionResetError",
                "BrokenPipeError",
            ],
        )
        
        logger.info(f"Sentry initialized for environment: {environment}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize Sentry: {e}")
        return False


def filter_sensitive_data(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Filter sensitive data from Sentry events.
    """
    # List of sensitive keys to redact
    sensitive_keys = [
        "password", "token", "secret", "api_key", "authorization",
        "jwt", "access_token", "refresh_token", "cookie"
    ]
    
    def redact_dict(d: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(d, dict):
            return d
        
        result = {}
        for key, value in d.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                result[key] = "[REDACTED]"
            elif isinstance(value, dict):
                result[key] = redact_dict(value)
            elif isinstance(value, list):
                result[key] = [redact_dict(v) if isinstance(v, dict) else v for v in value]
            else:
                result[key] = value
        return result
    
    # Redact request data
    if "request" in event:
        if "headers" in event["request"]:
            event["request"]["headers"] = redact_dict(event["request"]["headers"])
        if "data" in event["request"]:
            event["request"]["data"] = redact_dict(event["request"]["data"])
    
    # Redact extra data
    if "extra" in event:
        event["extra"] = redact_dict(event["extra"])
    
    return event


def capture_exception(exception: Exception, **kwargs) -> Optional[str]:
    """
    Capture an exception to Sentry.
    
    Args:
        exception: The exception to capture
        **kwargs: Additional context
    
    Returns:
        Event ID if captured, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None
    
    try:
        with sentry_sdk.push_scope() as scope:
            for key, value in kwargs.items():
                scope.set_extra(key, value)
            return sentry_sdk.capture_exception(exception)
    except Exception as e:
        logger.error(f"Failed to capture exception to Sentry: {e}")
        return None


def capture_message(message: str, level: str = "info", **kwargs) -> Optional[str]:
    """
    Capture a message to Sentry.
    
    Args:
        message: The message to capture
        level: Log level (debug, info, warning, error, fatal)
        **kwargs: Additional context
    
    Returns:
        Event ID if captured, None otherwise
    """
    if not SENTRY_AVAILABLE:
        return None
    
    try:
        with sentry_sdk.push_scope() as scope:
            for key, value in kwargs.items():
                scope.set_extra(key, value)
            return sentry_sdk.capture_message(message, level=level)
    except Exception as e:
        logger.error(f"Failed to capture message to Sentry: {e}")
        return None


def set_user(user_id: str, email: Optional[str] = None, role: Optional[str] = None):
    """
    Set user context for Sentry.
    """
    if not SENTRY_AVAILABLE:
        return
    
    sentry_sdk.set_user({
        "id": user_id,
        "email": email,
        "role": role,
    })


def set_tag(key: str, value: str):
    """Set a tag for Sentry."""
    if SENTRY_AVAILABLE:
        sentry_sdk.set_tag(key, value)


def set_context(name: str, context: Dict[str, Any]):
    """Set context for Sentry."""
    if SENTRY_AVAILABLE:
        sentry_sdk.set_context(name, context)
