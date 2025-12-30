import asyncpg
import asyncio

async def main():
    conn = await asyncpg.connect('postgresql://postgres@localhost/ats')
    result = await conn.fetch("""
        SELECT column_name, data_type, is_nullable 
        FROM information_schema.columns 
        WHERE table_name='company_research_jobs' 
        ORDER BY ordinal_position
    """)
    print("Column Name          Data Type                      Nullable")
    print("-" * 70)
    for row in result:
        print(f'{row[0]:20} {row[1]:30} {row[2]}')
    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())