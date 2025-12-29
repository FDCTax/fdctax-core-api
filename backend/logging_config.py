"""
FDC Core - Structured JSON Logging

Provides structured logging for production environments.
Outputs JSON format for log aggregation (Datadog, CloudWatch, etc.)
"""

import logging
import json
import sys
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import traceback


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs JSON logs.
    Compatible with log aggregation services.
    """
    
    def __init__(self, service_name: str = "fdc-core"):
        super().__init__()
        self.service_name = service_name
        self.environment = os.environ.get("ENVIRONMENT", "development")
        self.hostname = os.environ.get("HOSTNAME", "unknown")
    
    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment,
            "hostname": self.hostname,
        }
        
        # Add location info
        log_data["location"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None,
            }
        
        # Add extra fields
        extra_fields = {
            key: value for key, value in record.__dict__.items()
            if key not in [
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "taskName"
            ]
        }
        if extra_fields:
            log_data["extra"] = extra_fields
        
        return json.dumps(log_data, default=str)


class RequestContextFilter(logging.Filter):
    """
    Adds request context to log records.
    """
    
    def __init__(self):
        super().__init__()
        self._request_id: Optional[str] = None
        self._user_id: Optional[str] = None
        self._user_email: Optional[str] = None
    
    def set_request_context(
        self,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None
    ):
        self._request_id = request_id
        self._user_id = user_id
        self._user_email = user_email
    
    def clear_request_context(self):
        self._request_id = None
        self._user_id = None
        self._user_email = None
    
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = self._request_id
        record.user_id = self._user_id
        record.user_email = self._user_email
        return True


def setup_logging(
    level: str = "INFO",
    json_format: bool = True,
    service_name: str = "fdc-core"
) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_format: Use JSON format (True for production)
        service_name: Service name for log aggregation
    
    Returns:
        Configured root logger
    """
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    # Set formatter based on environment
    if json_format:
        handler.setFormatter(JSONFormatter(service_name=service_name))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
    
    # Add request context filter
    context_filter = RequestContextFilter()
    handler.addFilter(context_filter)
    
    # Add handler
    root_logger.addHandler(handler)
    
    # Suppress noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return root_logger


# Convenience function to get logger with context
def get_logger(name: str) -> logging.Logger:
    """Get a logger with the specified name."""
    return logging.getLogger(name)


# Global request context filter instance
_request_context_filter: Optional[RequestContextFilter] = None


def set_request_context(
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None
):
    """Set request context for logging."""
    global _request_context_filter
    if _request_context_filter:
        _request_context_filter.set_request_context(request_id, user_id, user_email)


def clear_request_context():
    """Clear request context."""
    global _request_context_filter
    if _request_context_filter:
        _request_context_filter.clear_request_context()
