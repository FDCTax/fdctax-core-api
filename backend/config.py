"""
FDC Core - Configuration Management

Centralized configuration for environment variables, CORS, and deployment settings.
This module ensures:
- No hardcoded secrets
- No missing required variables
- Environment-specific settings (dev/staging/prod)
- Secure defaults
"""

import os
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Uses pydantic-settings for validation and type coercion.
    """
    
    # ==================== ENVIRONMENT ====================
    ENVIRONMENT: str = Field(
        default="development",
        description="Runtime environment: development, staging, production"
    )
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode (auto-enabled in development)"
    )
    
    # ==================== DATABASE ====================
    # PostgreSQL (Primary)
    DATABASE_URL: str = Field(
        default="",
        description="PostgreSQL connection URL (required)"
    )
    POSTGRES_HOST: str = Field(default="")
    POSTGRES_PORT: int = Field(default=25060)
    POSTGRES_DB: str = Field(default="defaultdb")
    POSTGRES_USER: str = Field(default="")
    POSTGRES_PASSWORD: str = Field(default="")
    POSTGRES_SSLMODE: str = Field(default="require")
    
    # MongoDB (Legacy - being phased out)
    MONGO_URL: str = Field(
        default="mongodb://localhost:27017",
        description="MongoDB connection URL (legacy services)"
    )
    DB_NAME: str = Field(
        default="fdc_tax_crm",
        description="MongoDB database name"
    )
    
    # ==================== AUTHENTICATION ====================
    JWT_SECRET_KEY: str = Field(
        default="",
        description="Secret key for JWT signing (required, must be changed in production)"
    )
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        description="Access token expiry in minutes"
    )
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7,
        description="Refresh token expiry in days"
    )
    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="JWT signing algorithm"
    )
    
    # ==================== CORS ====================
    CORS_ORIGINS: str = Field(
        default="",
        description="Comma-separated list of allowed origins"
    )
    
    # ==================== STORAGE ====================
    STORAGE_REF_BASE: str = Field(
        default="local://uploads",
        description="Base path for file storage (future: s3://bucket-name)"
    )
    UPLOAD_MAX_SIZE_MB: int = Field(
        default=50,
        description="Maximum upload file size in MB"
    )
    
    # ==================== INTEGRATIONS ====================
    CALENDLY_PAT: str = Field(
        default="",
        description="Calendly Personal Access Token"
    )
    CALENDLY_WEBHOOK_SECRET: str = Field(
        default="",
        description="Calendly webhook signing secret"
    )
    
    # ==================== OBSERVABILITY ====================
    SENTRY_DSN: str = Field(
        default="",
        description="Sentry DSN for error tracking"
    )
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level: DEBUG, INFO, WARNING, ERROR"
    )
    
    # ==================== API ====================
    API_RATE_LIMIT: int = Field(
        default=100,
        description="Rate limit per minute per IP"
    )
    API_TITLE: str = Field(
        default="FDC Tax Core + CRM Sync API",
        description="API title for OpenAPI docs"
    )
    API_VERSION: str = Field(
        default="1.0.0",
        description="API version"
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
    
    # ==================== COMPUTED PROPERTIES ====================
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"
    
    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() == "development"
    
    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT.lower() == "staging"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """
        Parse CORS_ORIGINS into a list with environment-aware defaults.
        
        Production/Staging: Only specified origins
        Development: Include localhost origins
        """
        if self.CORS_ORIGINS and self.CORS_ORIGINS != "*":
            origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        else:
            origins = []
        
        # Production origins (always allowed)
        production_origins = [
            "https://fdctax.com",
            "https://www.fdctax.com",
            "https://myfdc.com",
            "https://www.myfdc.com",
            "https://api.fdccore.com",
            "https://backend.fdctax.com",
        ]
        
        # Development origins (only in dev/staging)
        dev_origins = [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
        
        # Combine based on environment
        all_origins = set(origins + production_origins)
        
        if not self.is_production:
            all_origins.update(dev_origins)
        
        return list(all_origins)
    
    @property
    def debug_enabled(self) -> bool:
        """Enable debug in development or when explicitly set"""
        return self.DEBUG or self.is_development
    
    def validate_production_config(self) -> List[str]:
        """
        Validate configuration for production deployment.
        Returns list of validation errors.
        """
        errors = []
        
        # Required variables
        if not self.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        
        if not self.JWT_SECRET_KEY:
            errors.append("JWT_SECRET_KEY is required")
        elif self.JWT_SECRET_KEY == "fdc-tax-crm-production-secret-key-2025-change-me":
            errors.append("JWT_SECRET_KEY must be changed from default value")
        elif len(self.JWT_SECRET_KEY) < 32:
            errors.append("JWT_SECRET_KEY should be at least 32 characters")
        
        # Production-specific checks
        if self.is_production:
            if self.CORS_ORIGINS == "*":
                errors.append("CORS_ORIGINS cannot be '*' in production")
            
            if "localhost" in self.DATABASE_URL.lower():
                errors.append("DATABASE_URL cannot point to localhost in production")
            
            if self.DEBUG:
                errors.append("DEBUG should be False in production")
        
        return errors
    
    def get_database_url(self) -> str:
        """Get the appropriate database URL"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        
        # Build from components if DATABASE_URL not set
        if self.POSTGRES_HOST and self.POSTGRES_USER and self.POSTGRES_PASSWORD:
            ssl = f"?ssl={self.POSTGRES_SSLMODE}" if self.POSTGRES_SSLMODE else ""
            return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}{ssl}"
        
        raise ValueError("No database configuration found. Set DATABASE_URL or POSTGRES_* variables.")


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Settings are loaded once and cached for the application lifetime.
    """
    settings = Settings()
    
    # Log configuration status
    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug: {settings.debug_enabled}")
    logger.info(f"CORS Origins: {len(settings.cors_origins_list)} configured")
    
    # Validate in production
    if settings.is_production:
        errors = settings.validate_production_config()
        if errors:
            for error in errors:
                logger.error(f"Configuration error: {error}")
            raise ValueError(f"Production configuration invalid: {', '.join(errors)}")
    
    return settings


# ==================== CORS CONFIGURATION ====================

def get_cors_config() -> dict:
    """
    Get CORS middleware configuration.
    
    Returns configuration dict for CORSMiddleware.
    """
    settings = get_settings()
    
    return {
        "allow_origins": settings.cors_origins_list,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-Request-ID",
        ],
        "expose_headers": [
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
        ],
        "max_age": 600,  # Cache preflight for 10 minutes
    }


# ==================== ENVIRONMENT VALIDATION ====================

def validate_environment() -> dict:
    """
    Validate all required environment variables.
    
    Returns a status dict with validation results.
    """
    settings = get_settings()
    
    status = {
        "valid": True,
        "environment": settings.ENVIRONMENT,
        "errors": [],
        "warnings": [],
        "variables": {}
    }
    
    # Check required variables
    required_vars = [
        ("DATABASE_URL", settings.DATABASE_URL),
        ("JWT_SECRET_KEY", settings.JWT_SECRET_KEY),
    ]
    
    for name, value in required_vars:
        if not value:
            status["errors"].append(f"{name} is not set")
            status["valid"] = False
        else:
            status["variables"][name] = "✓ Set"
    
    # Check optional but recommended
    optional_vars = [
        ("SENTRY_DSN", settings.SENTRY_DSN, "Error tracking disabled"),
        ("CALENDLY_PAT", settings.CALENDLY_PAT, "Calendly integration disabled"),
        ("CALENDLY_WEBHOOK_SECRET", settings.CALENDLY_WEBHOOK_SECRET, "Webhook signature validation disabled"),
    ]
    
    for name, value, warning in optional_vars:
        if not value:
            status["warnings"].append(warning)
            status["variables"][name] = "⚠ Not set"
        else:
            status["variables"][name] = "✓ Set"
    
    # Production-specific validation
    errors = settings.validate_production_config()
    if errors:
        status["errors"].extend(errors)
        status["valid"] = False
    
    return status


# Export settings instance for convenience
settings = get_settings()
