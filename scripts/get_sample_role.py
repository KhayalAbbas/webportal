"""Get a sample role ID for testing."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text


async def get_role():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT id, title FROM role LIMIT 1"))
        row = result.fetchone()
        if row:
            print(f"Sample role ID: {row[0]}")
            print(f"Title: {row[1]}")
            return row[0]
        else:
            print("No roles found in database")
            print("You may need to run seed scripts first")
            return None


if __name__ == "__main__":
    asyncio.run(get_role())
