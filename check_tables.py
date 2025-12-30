import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import Settings
import psycopg2

settings = Settings()
# Convert asyncpg URL to psycopg2 format
db_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY table_name")
tables = cur.fetchall()
print("Tables in database:")
for table in tables:
    print(f"- {table[0]}")
conn.close()