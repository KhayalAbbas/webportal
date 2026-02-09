"""Drop and recreate ats_db for a clean migration run."""
import asyncio
import os
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL":
                os.environ["DATABASE_URL"] = value.strip().strip('"').strip("'")
                break

import asyncpg

url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
url = re.sub(r"/([^/?]+)(\?.*)?$", r"/postgres\2", url)

async def main():
    conn = await asyncpg.connect(url)
    await conn.execute("DROP DATABASE IF EXISTS ats_db")
    await conn.execute("CREATE DATABASE ats_db")
    await conn.close()
    print("Database ats_db recreated.")

if __name__ == "__main__":
    asyncio.run(main())
