"""
Application configuration settings.

This file loads settings from environment variables.
For local development, create a .env file based on .env.example
"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Attributes:
        DATABASE_URL: PostgreSQL connection string for async connection
        APP_NAME: Name of the application
        DEBUG: Enable debug mode (True for development, False for production)
    """
    
    # Database connection string
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    DATABASE_URL: str
    
    # Application settings
    APP_NAME: str = "ATS Research Engine"
    DEBUG: bool = False
    
    # JWT Authentication
    SECRET_KEY: str = "your-secret-key-change-this-in-production-min-32-chars"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # Operational limits / defaults (override via env)
    EXPORT_PACK_MAX_ZIP_BYTES: int = 25 * 1024 * 1024
    EXPORT_PACK_DEFAULT_MAX_COMPANIES: int = 500
    EXPORT_PACK_DEFAULT_MAX_EXECUTIVES: int = 2000
    EXPORT_PACK_MAX_COMPANIES: int = 2000
    EXPORT_PACK_MAX_EXECUTIVES: int = 5000
    EXPORT_PACK_STORAGE_ROOT: str = "artifacts/export_packs"
    EVIDENCE_BUNDLE_MAX_ZIP_BYTES: int = 25 * 1024 * 1024
    BULK_ENRICH_MAX_EXECUTIVES: int = 20

    # External search providers (Phase 9.3)
    GOOGLE_CSE_API_KEY: Optional[str] = None
    GOOGLE_CSE_CX: Optional[str] = None
    
    class Config:
        # Load variables from .env file if it exists
        env_file = ".env"
        env_file_encoding = "utf-8"


# Create a single settings instance to use throughout the app
settings = Settings()
