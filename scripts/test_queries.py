"""
Quick verification that models and DB schema are aligned.

Tests basic queries that were failing before the UUID migration.
"""

import asyncio
import pytest

pytestmark = pytest.mark.asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal
from app.models.role import Role
from app.models.company import Company
from app.models.candidate_assignment import CandidateAssignment
from app.models.candidate import Candidate
from app.models.bd_opportunity import BDOpportunity
from app.models.task import Task
from app.models.tenant import Tenant


async def test_queries():
    """Test the exact queries that were failing before."""
    
    print("="*80)
    print("DATABASE QUERY VERIFICATION")
    print("="*80)
    print()
    
    async with AsyncSessionLocal() as db:
        # Get a tenant for filtering
        result = await db.execute(select(Tenant).limit(1))
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            print("❌ No tenant found. Run seed_test_data.py first.")
            return False
        
        print(f"✅ Using tenant: {tenant.id} ({tenant.name})")
        print()
        
        all_passed = True
        
        # Test 1: The problematic dashboard query (roles + candidate_assignment join)
        print("Test 1: Roles with candidate counts (dashboard query)")
        print("-" * 80)
        try:
            query = (
                select(
                    Role,
                    Company.name.label("company_name"),
                    func.count(CandidateAssignment.id).label("candidate_count")
                )
                .join(Company, Company.id == Role.company_id)
                .outerjoin(CandidateAssignment, CandidateAssignment.role_id == Role.id)
                .where(Role.tenant_id == tenant.id)
                .group_by(Role.id, Company.name)
                .limit(10)
            )
            
            result = await db.execute(query)
            roles = result.all()
            
            print(f"✅ Query executed successfully")
            print(f"   Found {len(roles)} roles")
            for row in roles[:3]:
                role, company_name, count = row[0], row[1], row[2]
                print(f"   - {role.title} at {company_name} ({count} candidates)")
        except Exception as e:
            print(f"❌ Query failed: {type(e).__name__}: {e}")
            all_passed = False
        
        print()
        
        # Test 2: Candidates query
        print("Test 2: Candidates query")
        print("-" * 80)
        try:
            query = select(Candidate).where(Candidate.tenant_id == tenant.id).limit(5)
            result = await db.execute(query)
            candidates = result.scalars().all()
            
            print(f"✅ Query executed successfully")
            print(f"   Found {len(candidates)} candidates")
            for candidate in candidates[:3]:
                print(f"   - {candidate.first_name} {candidate.last_name}")
        except Exception as e:
            print(f"❌ Query failed: {type(e).__name__}: {e}")
            all_passed = False
        
        print()
        
        # Test 3: BD Opportunities with company join
        print("Test 3: BD Opportunities with company join")
        print("-" * 80)
        try:
            query = (
                select(BDOpportunity, Company.name.label("company_name"))
                .join(Company, BDOpportunity.company_id == Company.id)
                .where(BDOpportunity.tenant_id == tenant.id)
                .limit(5)
            )
            result = await db.execute(query)
            opportunities = result.all()
            
            print(f"✅ Query executed successfully")
            print(f"   Found {len(opportunities)} BD opportunities")
            for row in opportunities[:3]:
                opp, company_name = row[0], row[1]
                print(f"   - {opp.stage} at {company_name} ({opp.status})")
        except Exception as e:
            print(f"❌ Query failed: {type(e).__name__}: {e}")
            all_passed = False
        
        print()
        
        # Test 4: Tasks query
        print("Test 4: Tasks query")
        print("-" * 80)
        try:
            query = select(Task).where(Task.tenant_id == tenant.id).limit(5)
            result = await db.execute(query)
            tasks = result.scalars().all()
            
            print(f"✅ Query executed successfully")
            print(f"   Found {len(tasks)} tasks")
            for task in tasks[:3]:
                print(f"   - {task.title} ({task.status})")
        except Exception as e:
            print(f"❌ Query failed: {type(e).__name__}: {e}")
            all_passed = False
        
        print()
        print("="*80)
        
        return all_passed


if __name__ == "__main__":
    success = asyncio.run(test_queries())
    
    if success:
        print("✅ ALL QUERIES PASSED - UUID migration successful!")
        print("="*80)
        sys.exit(0)
    else:
        print("❌ SOME QUERIES FAILED - check errors above")
        print("="*80)
        sys.exit(1)
