import asyncio
from app.database import get_session
from sqlalchemy import text

async def check_jobs():
    async with get_session() as db:
        result = await db.execute(text('SELECT COUNT(*) FROM research_jobs'))
        count = result.scalar()
        print(f'✅ Jobs in queue: {count}')
        
        # Show job details if any exist
        result = await db.execute(text('''
            SELECT id, job_type, status, attempts, created_at 
            FROM research_jobs 
            ORDER BY created_at DESC 
            LIMIT 5
        '''))
        jobs = result.fetchall()
        
        if jobs:
            print('Recent jobs:')
            for job in jobs:
                print(f'  {job[0]}: {job[1]} - {job[2]} (attempt {job[3]}) - {job[4]}')
        else:
            print('No jobs found')

if __name__ == "__main__":
    asyncio.run(check_jobs())