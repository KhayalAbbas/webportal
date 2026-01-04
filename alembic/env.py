"""
Alembic environment configuration.

This file configures how Alembic connects to the database
and how it generates migrations.
"""

import sys
from pathlib import Path

# Add the project root to sys.path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import your database Base and all models
# This is important so Alembic knows about your tables
from app.db.base import Base
from app.models import (
    Tenant,
    User,
    Company,
    Contact,
    Candidate,
    Role,
    PipelineStage,
    ActivityLog,
    ResearchEvent,
    SourceDocument,
    AIEnrichmentRecord,
    CandidateContactPoint,
    CandidateAssignment,
    AssessmentResult,
    Task,
    List,
    ListItem,
    BDOpportunity,
)

# Import settings to get DATABASE_URL
from app.core.config import settings

# Alembic Config object - gives access to values in alembic.ini
config = context.config

# Set the database URL from our settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is the metadata that Alembic uses to detect changes
# It contains all the table definitions from your models
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    
    This generates SQL scripts without actually connecting to the database.
    Useful for reviewing what will be executed.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Helper to run migrations with a database connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Run migrations in 'online' mode with async engine.
    
    This connects to the database and applies migrations.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


# Decide which mode to run based on context
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
