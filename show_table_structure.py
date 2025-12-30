from app.db.session import async_session_maker
from sqlalchemy import text
import asyncio

async def main():
    async with async_session_maker() as session:
        result = await session.execute(text("""
            SELECT column_name, data_type, is_nullable 
            FROM information_schema.columns 
            WHERE table_name='research_jobs' 
            ORDER BY ordinal_position
        """))
        print("Column Name          Data Type                      Nullable")
        print("-" * 70)
        for row in result:
            print(f'{row[0]:20} {row[1]:30} {row[2]}')

if __name__ == "__main__":
    asyncio.run(main())