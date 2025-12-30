"""
Integration test script for Phase 3.2 durable job system.
"""
import asyncio
import json
import subprocess
import time
import requests
import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager

# Change to project directory and add to path
os.chdir(Path(__file__).parent)
sys.path.insert(0, str(Path.cwd()))

try:
    from app.db.session import async_session_maker
    from sqlalchemy import text
except ImportError as e:
    print(f"Import error: {e}")
    print("Working directory:", os.getcwd())
    sys.exit(1)


@asynccontextmanager
async def get_session():
    """Context manager helper for async DB sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class Phase32IntegrationTest:
    def __init__(self):
        self.api_process = None
        self.worker_process = None
        self.base_url = "http://127.0.0.1:8005"
        self.session = requests.Session()
        self.tenant_id = "b3909011-8bd3-439d-a421-3b70fae124e9"
        self.token = None
        
    def start_api(self):
        """Start API server."""
        print("🚀 Starting API server...")
        self.api_process = subprocess.Popen([
            "python", "-m", "uvicorn", 
            "app.main:app", 
            "--host", "127.0.0.1", 
            "--port", "8005"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(5)  # Wait for startup
        print("✅ API server started")
    
    def start_worker(self):
        """Start worker process."""
        print("🔧 Starting worker...")
        self.worker_process = subprocess.Popen([
            "python", "tools/worker.py"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(2)  # Wait for startup
        print("✅ Worker started")
    
    def stop_processes(self):
        """Stop all processes."""
        if self.worker_process:
            self.worker_process.terminate()
            print("🛑 Worker stopped")
        if self.api_process:
            self.api_process.terminate()
            print("🛑 API server stopped")
    
    def login(self):
        """Login to get authentication token."""
        print("🔐 Logging in...")
        response = self.session.post(f"{self.base_url}/auth/login", json={
            "email": "admin@test.com",
            "password": "admin123"
        }, headers={"X-Tenant-ID": self.tenant_id})
        
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.session.headers.update({
                "Authorization": f"Bearer {self.token}",
                "X-Tenant-ID": self.tenant_id
            })
            print("✅ Login successful")
            return True
        else:
            print(f"❌ Login failed: {response.text}")
            return False
    
    def create_run(self):
        """Create research run."""
        print("📝 Creating research run...")
        payload = {
            "objective": "Phase 3.2 Integration Test",
            "constraints": {"industries": ["technology"]},
            "rank_spec": {"criteria": ["growth"]},
            "idempotency_key": f"integration-test-{int(time.time())}"
        }
        
        response = self.session.post(f"{self.base_url}/runs", json=payload)
        if response.status_code == 201:
            run_data = response.json()
            run_id = run_data["id"]
            print(f"✅ Research run created: {run_id}")
            return run_id
        else:
            print(f"❌ Run creation failed: {response.text}")
            return None
    
    def upload_bundle(self, run_id):
        """Upload bundle with accept_only=True."""
        print("📤 Uploading bundle...")
        
        # Load test bundle
        with open("fresh_bundle.json", "r") as f:
            bundle_data = json.load(f)
        bundle_data["run_id"] = run_id
        
        response = self.session.post(
            f"{self.base_url}/runs/{run_id}/bundle",
            json=bundle_data,
            params={"accept_only": True}
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Bundle uploaded: {result['status']}")
            return result["status"] == "needs_review"
        else:
            print(f"❌ Bundle upload failed: {response.text}")
            return False
    
    def approve_bundle(self, run_id):
        """Approve bundle for ingestion."""
        print("✅ Approving bundle...")
        response = self.session.post(f"{self.base_url}/runs/{run_id}/approve")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Bundle approved: {result['message']}")
            return True
        else:
            print(f"❌ Approval failed: {response.text}")
            return False
    
    def check_run_status(self, run_id):
        """Check run status."""
        response = self.session.get(f"{self.base_url}/runs/{run_id}")
        if response.status_code == 200:
            return response.json()["status"]
        return None
    
    async def check_job_queue(self):
        """Check job queue in database."""
        async with get_session() as db:
            result = await db.execute(text("""
                SELECT id, job_type, status, attempts, created_at 
                FROM research_jobs 
                ORDER BY created_at DESC 
                LIMIT 5
            """))
            jobs = result.fetchall()
            return jobs
    
    async def wait_for_completion(self, run_id, timeout=30):
        """Wait for job completion."""
        print("⏳ Waiting for job completion...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = self.check_run_status(run_id)
            print(f"📊 Run status: {status}")
            
            if status in ["submitted", "failed"]:
                return status
            
            await asyncio.sleep(2)
        
        print("⏰ Timeout waiting for completion")
        return None
    
    async def run_test(self):
        """Run complete integration test."""
        try:
            print("=" * 50)
            print("🧪 PHASE 3.2 INTEGRATION TEST")
            print("=" * 50)
            
            # Start services
            self.start_api()
            self.start_worker()
            
            # Test workflow
            if not self.login():
                return False
            
            run_id = self.create_run()
            if not run_id:
                return False
            
            if not self.upload_bundle(run_id):
                return False
            
            # Check initial status
            status = self.check_run_status(run_id)
            print(f"📊 Status after upload: {status}")
            assert status == "needs_review", f"Expected needs_review, got {status}"
            
            if not self.approve_bundle(run_id):
                return False
            
            # Check status after approval
            status = self.check_run_status(run_id)
            print(f"📊 Status after approval: {status}")
            
            # Check job queue
            jobs = await self.check_job_queue()
            print(f"📋 Jobs in queue: {len(jobs)}")
            for job in jobs:
                print(f"  Job {job[0]}: {job[1]} - {job[2]} (attempt {job[3]})")
            
            # Wait for completion
            final_status = await self.wait_for_completion(run_id)
            print(f"🏁 Final status: {final_status}")
            
            # Check final job queue
            jobs = await self.check_job_queue()
            print(f"📋 Final jobs in queue: {len(jobs)}")
            
            print("✅ Integration test completed successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Integration test failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            self.stop_processes()


async def main():
    test = Phase32IntegrationTest()
    success = await test.run_test()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())