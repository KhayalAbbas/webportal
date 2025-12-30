"""Check research events for debug info."""
import asyncio
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.company_research import CompanyResearchEvent


async def check_events():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get recent extract events
        result = await session.execute(
            select(CompanyResearchEvent)
            .where(CompanyResearchEvent.event_type == 'extract')
            .order_by(CompanyResearchEvent.created_at.desc())
            .limit(5)
        )
        events = result.scalars().all()
        
        print(f"\nFound {len(events)} recent extraction events:\n")
        
        for event in events:
            print(f"Event ID: {event.id}")
            print(f"  Status: {event.status}")
            print(f"  Created: {event.created_at}")
            
            if event.input_json:
                print(f"  Input (debug info):")
                input_data = json.loads(event.input_json) if isinstance(event.input_json, str) else event.input_json
                for key, value in input_data.items():
                    if key == 'sample_text':
                        print(f"    {key}: {value[:100]}...")
                    elif key == 'first_lines':
                        print(f"    {key}: {value[:3]}")
                    else:
                        print(f"    {key}: {value}")
            
            if event.output_json:
                print(f"  Output:")
                output_data = json.loads(event.output_json) if isinstance(event.output_json, str) else event.output_json
                print(f"    companies_found: {output_data.get('companies_found')}")
                if 'companies' in output_data and output_data['companies']:
                    print(f"    First few companies:")
                    for company in output_data['companies'][:3]:
                        print(f"      - {company.get('name', 'N/A')[:60]}")
            
            print()
    
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_events())
