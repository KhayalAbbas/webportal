"""
Health check router.

Provides endpoints to check if the API and database are working.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.session import get_db

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Basic health check.
    
    Returns OK if the API is running.
    """
    return {"status": "ok", "message": "API is running"}


@router.get("/health/db")
async def database_health_check(db: AsyncSession = Depends(get_db)):
    """
    Database health check.
    
    Returns OK if the database connection is working.
    """
    try:
        # Try to execute a simple query
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "message": "Database connection is working"}
    except Exception as e:
        return {"status": "error", "message": f"Database error: {str(e)}"}
