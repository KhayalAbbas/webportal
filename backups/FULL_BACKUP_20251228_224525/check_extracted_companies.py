import asyncio
import sys
sys.path.insert(0, 'C:/ATS')

from sqlalchemy import select, text
from app.db.session import async_session_maker
from app.models.company_research import CompanyProspect

async def check_companies():
    """Check what companies were extracted from the latest run"""
    
    async with async_session_maker() as session:
        # Get companies from the run
        result = await session.execute(
            select(CompanyProspect)
            .where(CompanyProspect.company_research_run_id == 'b453d622-ad90-4bdd-a29a-eb6ee2a04ea2')
            .order_by(CompanyProspect.created_at.desc())
            .limit(50)
        )
        companies = result.scalars().all()
        
        print(f"\n{'='*80}")
        print(f"Found {len(companies)} companies")
        print(f"{'='*80}\n")
        
        for i, company in enumerate(companies, 1):
            print(f"{i:3}. {company.name_raw}")
        
        print(f"\n{'='*80}")
        
        # Show some details for first 10
        print(f"\nFirst 10 with details:")
        for i, company in enumerate(companies[:10], 1):
            print(f"\n{i}. '{company.name_raw}'")
            print(f"   Normalized: '{company.name_normalized}'")

if __name__ == "__main__":
    asyncio.run(check_companies())
