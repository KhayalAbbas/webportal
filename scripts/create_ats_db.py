"""
Create the ats_db database if it doesn't exist.

Uses DATABASE_URL from .env but connects to the default 'postgres' database
to run CREATE DATABASE ats_db.

Usage (from project root):
    python scripts/create_ats_db.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

# Load .env from project root
root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key == "DATABASE_URL":
                os.environ["DATABASE_URL"] = value
                break

try:
    import asyncpg
except ImportError:
    print("asyncpg is required. Run: pip install asyncpg")
    sys.exit(1)


def get_connection_url_to_postgres():
    """Get a connection URL pointing to the 'postgres' database (default DB)."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set. Add it to your .env file.")
        sys.exit(1)
    # postgresql+asyncpg://user:pass@host:port/ats_db -> postgresql://user:pass@host:port/postgres
    url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", url)
    # Replace database name with 'postgres' so we can connect to create ats_db
    url = re.sub(r"/([^/?]+)(\?.*)?$", r"/postgres\2", url)
    return url


async def main():
    url = get_connection_url_to_postgres()
    try:
        conn = await asyncpg.connect(url)
    except Exception as e:
        print(f"ERROR: Could not connect to PostgreSQL: {e}")
        print("Check that PostgreSQL is running and DATABASE_URL in .env has the correct password.")
        sys.exit(1)

    try:
        await conn.execute("CREATE DATABASE ats_db")
        print("Database 'ats_db' created successfully.")
    except asyncpg.DuplicateDatabaseError:
        print("Database 'ats_db' already exists. Nothing to do.")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
