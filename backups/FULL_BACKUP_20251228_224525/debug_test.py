#!/usr/bin/env python3
"""Debug the database issue"""

import os
import sys
import time
import subprocess
import requests
import asyncio
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ats_db"

async def check_research_run(run_id_str):
    """Check the research run in database"""
    engine = create_async_engine(DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession)
    
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, company_research_run_id FROM research_runs WHERE id = :run_id"),
            {"run_id": uuid.UUID(run_id_str)}
        )
        row = result.fetchone()
        if row:
            print(f"Research run {run_id_str}:")
            print(f"  id: {row[0]}")
            print(f"  company_research_run_id: {row[1]}")
        else:
            print(f"Research run {run_id_str} not found")

def test_with_debug():
    # Start server
    env = os.environ.copy()
    env['DATABASE_URL'] = DATABASE_URL
    
    proc = subprocess.Popen([
        sys.executable, '-m', 'uvicorn', 'app.main:app', 
        '--host', '127.0.0.1', '--port', '8005'
    ], env=env)
    
    time.sleep(3)
    
    try:
        # Login
        session = requests.Session()
        login_resp = session.post('http://127.0.0.1:8005/login', data={
            'email': 'admin@test.com',
            'password': 'admin123', 
            'tenant_id': 'b3909011-8bd3-439d-a421-3b70fae124e9'
        })
        
        print(f"Login: {login_resp.status_code}")
        
        # Upload
        with open('fresh_bundle.json', 'rb') as f:
            resp = session.post('http://127.0.0.1:8005/ui/research/upload',
                data={'objective': 'Debug Test'},
                files={'bundle_file': f}
            )
        
        print(f"Upload: {resp.status_code}")
        
        # Extract run_id from response if possible
        import re
        run_id_match = re.search(r'([a-f0-9-]{36})', resp.text)
        if run_id_match:
            run_id = run_id_match.group(1)
            print(f"Found run_id: {run_id}")
            
            # Check the database
            asyncio.run(check_research_run(run_id))
        else:
            print("No run_id found in response")
            
    finally:
        proc.terminate()

if __name__ == "__main__":
    test_with_debug()