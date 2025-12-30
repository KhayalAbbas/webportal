import asyncio
from app.db.session import async_session_maker
from sqlalchemy import text

async def find_role():
    async with async_session_maker() as db:
        result = await db.execute(text('SELECT id FROM role LIMIT 5'))
        ids = [str(row.id) for row in result.fetchall()]
        print(f"Available role IDs: {ids}")
        return ids[0] if ids else None

if __name__ == "__main__":
    asyncio.run(find_role())