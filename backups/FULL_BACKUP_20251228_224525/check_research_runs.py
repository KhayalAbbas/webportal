"""
Check if research runs exist in database.
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, desc

from app.core.config import settings
from app.models.company_research import CompanyResearchRun

async def check_runs():
    """Check all research runs in database."""
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        result = await session.execute(
            select(CompanyResearchRun)
            .order_by(desc(CompanyResearchRun.created_at))
            .limit(10)
        )
        runs = result.scalars().all()
        
        print(f"\n=== Found {len(runs)} research runs ===\n")
        
        for run in runs:
            print(f"ID: {run.id}")
            print(f"Name: {run.name}")
            print(f"Status: {run.status}")
            print(f"Sector: {run.sector}")
            print(f"Created: {run.created_at}")
            print(f"Role Mandate ID: {run.role_mandate_id}")
            print(f"Tenant ID: {run.tenant_id}")
            print("-" * 60)

if __name__ == "__main__":
    asyncio.run(check_runs())
