"""
SQLAlchemy declarative base.

This is the foundation for all database models.
All models inherit from this Base class.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    
    All your database tables/models should inherit from this class.
    This allows SQLAlchemy to track and manage all your models together.
    """
    pass
