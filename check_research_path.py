import asyncio
import asyncpg

async def check_research_path():
    conn = await asyncpg.connect('postgresql://postgres@localhost/ats')
    
    # Check if we have a working research run
    runs = await conn.fetch("""
        SELECT id, company_id, status, created_at
        FROM company_research_runs
        ORDER BY created_at DESC
        LIMIT 3
    """)
    
    print("Available research runs:")
    for run in runs:
        print(f"  {run['id']} - company_id={run['company_id']} - status={run['status']}")
    
    if runs:
        run_id = runs[0]['id']
        company_id = runs[0]['company_id']
        
        # Check prospects for this run
        prospects = await conn.fetch("""
            SELECT COUNT(*) as count
            FROM company_prospects
            WHERE company_research_run_id = $1
        """, run_id)
        
        print(f"\nRun {run_id} has {prospects[0]['count']} prospects")
        return run_id, company_id
    else:
        # Create a basic research run
        company_id = 1
        result = await conn.fetchrow("""
            INSERT INTO company_research_runs (company_id, status)
            VALUES ($1, 'ready')
            RETURNING id
        """, company_id)
        run_id = result['id']
        print(f"Created new research run: {run_id}")
        return run_id, company_id
    
    await conn.close()

if __name__ == "__main__":
    run_id, company_id = asyncio.run(check_research_path())
    print(f"Ready to test with run_id={run_id}, company_id={company_id}")