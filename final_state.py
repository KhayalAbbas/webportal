from app.db.session import async_session_maker
from sqlalchemy import text
import asyncio

TENANT_ID = "44444444-4444-4444-4444-444444444444"
RUN_ID = "55555555-5555-5555-5555-555555555555"

async def final_state():
    async with async_session_maker() as session:
        # G) Final state
        result = await session.execute(text(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}'"))
        row = result.fetchone()
        print(f"SELECT id,status FROM research_runs WHERE id='{RUN_ID}';")
        print(f"{row[0]} | {row[1]}")
        
        result = await session.execute(text(f"SELECT id,status,attempts,max_attempts,retry_at,last_error FROM research_jobs WHERE run_id='{RUN_ID}' ORDER BY created_at DESC LIMIT 1"))
        row = result.fetchone()
        print(f"SELECT id,status,attempts,max_attempts,retry_at,last_error FROM research_jobs WHERE run_id='{RUN_ID}' ORDER BY created_at DESC LIMIT 1;")
        print(f"{row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5][:100] if row[5] else None}")
        
        result = await session.execute(text(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id='{TENANT_ID}'"))
        print(f"SELECT COUNT(*) FROM company_prospects WHERE tenant_id='{TENANT_ID}';")
        print(f"{result.scalar()}")

if __name__ == "__main__":
    asyncio.run(final_state())