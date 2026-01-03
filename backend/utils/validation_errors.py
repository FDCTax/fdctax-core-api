"""
Structured Validation Error Utilities

Provides standardized error responses for validation failures.
Helps UI distinguish between validation errors and connectivity issues.

Error Response Format:
{
    "error": "missing_parameter" | "invalid_parameter" | "validation_error",
    "parameter": "client_id",
    "message": "client_id is required"
}
"""

from fastapi import HTTPException, status
from typing import Optional, Any


class ValidationErrorResponse:
    """Structured validation error response builder."""
    
    @staticmethod
    def missing_parameter(parameter: str, message: Optional[str] = None) -> dict:
        """
        Create a missing parameter error response.
        
        Args:
            parameter: Name of the missing parameter
            message: Optional custom message
            
        Returns:
            Structured error dict
        """
        return {
            "error": "missing_parameter",
            "parameter": parameter,
            "message": message or f"{parameter} is required"
        }
    
    @staticmethod
    def invalid_parameter(parameter: str, message: str, value: Optional[Any] = None) -> dict:
        """
        Create an invalid parameter error response.
        
        Args:
            parameter: Name of the invalid parameter
            message: Description of the validation error
            value: The invalid value (optional, for debugging)
            
        Returns:
            Structured error dict
        """
        response = {
            "error": "invalid_parameter",
            "parameter": parameter,
            "message": message
        }
        if value is not None:
            response["received_value"] = str(value)[:100]  # Truncate for safety
        return response
    
    @staticmethod
    def validation_error(message: str, details: Optional[dict] = None) -> dict:
        """
        Create a general validation error response.
        
        Args:
            message: Description of the validation error
            details: Additional error details
            
        Returns:
            Structured error dict
        """
        response = {
            "error": "validation_error",
            "parameter": None,
            "message": message
        }
        if details:
            response["details"] = details
        return response


def raise_missing_parameter(parameter: str, message: Optional[str] = None):
    """
    Raise HTTPException with structured missing parameter error.
    
    Args:
        parameter: Name of the missing parameter
        message: Optional custom message
        
    Raises:
        HTTPException with 422 status and structured error body
    """
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=ValidationErrorResponse.missing_parameter(parameter, message)
    )


def raise_invalid_parameter(parameter: str, message: str, value: Optional[Any] = None):
    """
    Raise HTTPException with structured invalid parameter error.
    
    Args:
        parameter: Name of the invalid parameter
        message: Description of the validation error
        value: The invalid value (optional)
        
    Raises:
        HTTPException with 422 status and structured error body
    """
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=ValidationErrorResponse.invalid_parameter(parameter, message, value)
    )


def raise_validation_error(message: str, details: Optional[dict] = None):
    """
    Raise HTTPException with structured validation error.
    
    Args:
        message: Description of the validation error
        details: Additional error details
        
    Raises:
        HTTPException with 422 status and structured error body
    """
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=ValidationErrorResponse.validation_error(message, details)
    )


def validate_required_uuid(value: Optional[str], parameter: str) -> str:
    """
    Validate that a required UUID parameter is present and valid.
    
    Args:
        value: The value to validate
        parameter: Name of the parameter for error messages
        
    Returns:
        The validated value
        
    Raises:
        HTTPException with structured error if validation fails
    """
    import uuid
    
    if not value:
        raise_missing_parameter(parameter)
    
    try:
        # Validate UUID format
        uuid.UUID(value)
        return value
    except ValueError:
        raise_invalid_parameter(
            parameter,
            f"{parameter} must be a valid UUID format",
            value
        )


def validate_optional_uuid(value: Optional[str], parameter: str) -> Optional[str]:
    """
    Validate that an optional UUID parameter is valid if provided.
    
    Args:
        value: The value to validate (can be None)
        parameter: Name of the parameter for error messages
        
    Returns:
        The validated value or None
        
    Raises:
        HTTPException with structured error if validation fails
    """
    import uuid
    
    if not value:
        return None
    
    try:
        uuid.UUID(value)
        return value
    except ValueError:
        raise_invalid_parameter(
            parameter,
            f"{parameter} must be a valid UUID format",
            value
        )
