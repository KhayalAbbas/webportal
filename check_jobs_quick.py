import psycopg2, sys
from pathlib import Path
import os
sys.path.insert(0, "C:\\ATS")
from app.core.config import Settings
settings = Settings()
db_url = settings.DATABASE_URL.replace('postgresql+asyncpg://', 'postgresql://')
conn = psycopg2.connect(db_url)
cur = conn.cursor()
cur.execute('SELECT id, job_type, status FROM research_jobs ORDER BY created_at DESC LIMIT 10')
print('Recent jobs:')
for row in cur.fetchall():
    print(f'{row[0]} | {row[1]:20} | {row[2]}')
conn.close()