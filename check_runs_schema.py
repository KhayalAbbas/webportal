import psycopg2
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.core.config import Settings

settings = Settings()
db_url = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name = 'research_runs' ORDER BY ordinal_position")
print("research_runs table structure:")
for row in cur.fetchall():
    print(f'{row[0]:20} nullable={row[1]:5} default={row[2]}')
conn.close()