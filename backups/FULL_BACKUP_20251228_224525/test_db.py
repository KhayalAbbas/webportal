import asyncio
from app.db.session import AsyncSessionLocal

async def test_db():
    try:
        async with AsyncSessionLocal() as db:
            print("Database connected successfully!")
            return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_db())