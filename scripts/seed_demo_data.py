"""
Seed demo data into all main tables for UI exploration.

Run after migrations and optionally after seed_test_data.py.
Uses the first tenant in the DB (or creates one with a single user).

Usage:
    python scripts/seed_demo_data.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.models.user import User
from app.models.company import Company
from app.models.contact import Contact
from app.models.role import Role
from app.models.candidate import Candidate
from app.models.pipeline_stage import PipelineStage
from app.models.candidate_assignment import CandidateAssignment
from app.models.task import Task
from app.models.bd_opportunity import BDOpportunity
from app.models.list import List
from app.models.list_item import ListItem
from app.models.activity_log import ActivityLog
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


async def get_or_create_tenant(db: AsyncSession) -> Tenant:
    """Get first tenant or create a demo one with admin user."""
    result = await db.execute(
        select(Tenant).order_by(Tenant.created_at.asc()).limit(1)
    )
    tenant = result.scalar_one_or_none()
    if tenant:
        return tenant
    tenant = Tenant(name="Demo Company", status="active")
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)
    user_repo = UserRepository(db)
    admin = await user_repo.create(
        UserCreate(
            tenant_id=tenant.id,
            email="admin@test.com",
            full_name="Admin User",
            password="admin123",
            role="admin",
        )
    )
    print(f"[OK] Created tenant {tenant.name} and admin user {admin.email}")
    return tenant


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as db:
        tenant = await get_or_create_tenant(db)
        tid = tenant.id
        print(f"[OK] Using tenant: {tenant.name} ({tid})")

        # ---- Pipeline stages ----
        result = await db.execute(
            select(PipelineStage).where(PipelineStage.tenant_id == tid).limit(1)
        )
        if result.scalar_one_or_none() is None:
            stages = [
                PipelineStage(tenant_id=tid, code="SOURCED", name="Sourced", order_index=1),
                PipelineStage(tenant_id=tid, code="SCREENING", name="Screening", order_index=2),
                PipelineStage(tenant_id=tid, code="INTERVIEW", name="Interview", order_index=3),
                PipelineStage(tenant_id=tid, code="OFFER", name="Offer", order_index=4),
                PipelineStage(tenant_id=tid, code="HIRED", name="Hired", order_index=5),
            ]
            for s in stages:
                db.add(s)
            await db.flush()
            print("[OK] Created pipeline stages")
        else:
            stages_result = await db.execute(
                select(PipelineStage).where(PipelineStage.tenant_id == tid).order_by(PipelineStage.order_index)
            )
            stages = list(stages_result.scalars().all())
        stage_first = stages[0] if stages else None

        # ---- Companies ----
        result = await db.execute(select(Company).where(Company.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            c1 = Company(
                tenant_id=tid,
                name="Acme Corp",
                industry="Technology",
                headquarters_location="San Francisco, CA",
                website="https://acme.example.com",
                notes="Key client.",
                is_client=True,
                bd_status="active",
            )
            c2 = Company(
                tenant_id=tid,
                name="Global Finance Ltd",
                industry="Financial Services",
                headquarters_location="London, UK",
                website="https://globalfinance.example.com",
                is_prospect=True,
                bd_status="prospect",
            )
            c3 = Company(
                tenant_id=tid,
                name="HealthTech Solutions",
                industry="Healthcare",
                headquarters_location="Boston, MA",
                is_prospect=True,
            )
            db.add_all([c1, c2, c3])
            await db.flush()
            await db.refresh(c1)
            await db.refresh(c2)
            await db.refresh(c3)
            companies = [c1, c2, c3]
            print("[OK] Created companies: Acme Corp, Global Finance Ltd, HealthTech Solutions")
        else:
            companies_result = await db.execute(select(Company).where(Company.tenant_id == tid))
            companies = list(companies_result.scalars().all())
        c1, c2 = companies[0], companies[1] if len(companies) > 1 else companies[0]

        # ---- Contacts ----
        result = await db.execute(select(Contact).where(Contact.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            ct1 = Contact(
                tenant_id=tid,
                company_id=c1.id,
                first_name="Jane",
                last_name="Smith",
                email="jane.smith@acme.example.com",
                role_title="VP Engineering",
            )
            ct2 = Contact(
                tenant_id=tid,
                company_id=c1.id,
                first_name="John",
                last_name="Doe",
                email="john.doe@acme.example.com",
                role_title="HR Director",
            )
            ct3 = Contact(
                tenant_id=tid,
                company_id=c2.id,
                first_name="Alice",
                last_name="Brown",
                email="alice@globalfinance.example.com",
                role_title="Head of Talent",
            )
            db.add_all([ct1, ct2, ct3])
            await db.flush()
            await db.refresh(ct1)
            await db.refresh(ct2)
            await db.refresh(ct3)
            contacts = [ct1, ct2, ct3]
            print("[OK] Created contacts")
        else:
            contacts_result = await db.execute(select(Contact).where(Contact.tenant_id == tid))
            contacts = list(contacts_result.scalars().all())
        ct1 = contacts[0]

        # ---- Roles ----
        result = await db.execute(select(Role).where(Role.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            r1 = Role(
                tenant_id=tid,
                company_id=c1.id,
                title="Senior Software Engineer",
                function="Engineering",
                location="San Francisco (Hybrid)",
                status="open",
                seniority_level="Senior",
                description="Backend and APIs.",
            )
            r2 = Role(
                tenant_id=tid,
                company_id=c1.id,
                title="Product Manager",
                function="Product",
                location="Remote",
                status="open",
                seniority_level="Mid",
            )
            r3 = Role(
                tenant_id=tid,
                company_id=c2.id,
                title="Finance Director",
                function="Finance",
                status="on_hold",
            )
            db.add_all([r1, r2, r3])
            await db.flush()
            await db.refresh(r1)
            await db.refresh(r2)
            await db.refresh(r3)
            roles = [r1, r2, r3]
            print("[OK] Created roles")
        else:
            roles_result = await db.execute(select(Role).where(Role.tenant_id == tid))
            roles = list(roles_result.scalars().all())
        r1, r2 = roles[0], roles[1] if len(roles) > 1 else roles[0]

        # ---- Candidates ----
        result = await db.execute(select(Candidate).where(Candidate.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            cand1 = Candidate(
                tenant_id=tid,
                first_name="Michael",
                last_name="Johnson",
                email="michael.j@email.com",
                current_title="Software Engineer",
                current_company="Tech Co",
                location="Oakland, CA",
                tags="python,aws,backend",
            )
            cand2 = Candidate(
                tenant_id=tid,
                first_name="Sarah",
                last_name="Williams",
                email="sarah.w@email.com",
                current_title="Associate PM",
                current_company="Product Inc",
                location="New York, NY",
                tags="product,agile",
            )
            cand3 = Candidate(
                tenant_id=tid,
                first_name="David",
                last_name="Lee",
                email="david.lee@email.com",
                current_title="Finance Manager",
                current_company="Bank XYZ",
                location="London, UK",
            )
            db.add_all([cand1, cand2, cand3])
            await db.flush()
            await db.refresh(cand1)
            await db.refresh(cand2)
            await db.refresh(cand3)
            candidates = [cand1, cand2, cand3]
            print("[OK] Created candidates")
        else:
            candidates_result = await db.execute(select(Candidate).where(Candidate.tenant_id == tid))
            candidates = list(candidates_result.scalars().all())
        cand1, cand2 = candidates[0], candidates[1] if len(candidates) > 1 else candidates[0]

        # ---- Candidate assignments ----
        result = await db.execute(
            select(CandidateAssignment).where(CandidateAssignment.tenant_id == tid).limit(1)
        )
        if result.scalar_one_or_none() is None and stage_first:
            a1 = CandidateAssignment(
                tenant_id=tid,
                candidate_id=cand1.id,
                role_id=r1.id,
                current_stage_id=stage_first.id,
                status="active",
                is_hot=True,
                source="LinkedIn",
            )
            a2 = CandidateAssignment(
                tenant_id=tid,
                candidate_id=cand2.id,
                role_id=r2.id,
                current_stage_id=stage_first.id,
                status="active",
                source="Referral",
            )
            db.add_all([a1, a2])
            await db.flush()
            print("[OK] Created candidate assignments")
        elif result.scalar_one_or_none() is None:
            print("[SKIP] No pipeline stage for candidate assignments")

        # ---- Tasks ----
        result = await db.execute(select(Task).where(Task.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            now = datetime.utcnow()
            t1 = Task(
                tenant_id=tid,
                title="Schedule interview with Michael",
                description="First round with eng team",
                related_entity_type="candidate",
                status="pending",
                due_date=now + timedelta(days=7),
            )
            t2 = Task(
                tenant_id=tid,
                title="Send offer letter to Sarah",
                description="Comp and benefits",
                status="in_progress",
            )
            t3 = Task(
                tenant_id=tid,
                title="Follow up with Acme on role",
                status="completed",
                completed_at=now,
            )
            db.add_all([t1, t2, t3])
            await db.flush()
            print("[OK] Created tasks")
        else:
            print("[SKIP] Tasks already exist")

        # ---- BD Opportunities ----
        result = await db.execute(select(BDOpportunity).where(BDOpportunity.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            contact_for_c2 = next((c for c in contacts if c.company_id == c2.id), None)
            bd1 = BDOpportunity(
                tenant_id=tid,
                company_id=c2.id,
                contact_id=contact_for_c2.id if contact_for_c2 else None,
                status="open",
                stage="qualification",
                estimated_value=50000.00,
                currency="USD",
                probability=25,
            )
            bd2 = BDOpportunity(
                tenant_id=tid,
                company_id=c3.id,
                status="proposal",
                estimated_value=75000.00,
                currency="USD",
                probability=50,
            )
            db.add_all([bd1, bd2])
            await db.flush()
            print("[OK] Created BD opportunities")
        else:
            print("[SKIP] BD opportunities already exist")

        # ---- Lists and list items ----
        result = await db.execute(select(List).where(List.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None:
            lst = List(
                tenant_id=tid,
                name="Shortlist - Senior Eng",
                type="candidate",
                description="Top candidates for Senior Software Engineer",
            )
            db.add(lst)
            await db.flush()
            await db.refresh(lst)
            li1 = ListItem(
                tenant_id=tid,
                list_id=lst.id,
                entity_type="candidate",
                entity_id=cand1.id,
            )
            li2 = ListItem(
                tenant_id=tid,
                list_id=lst.id,
                entity_type="company",
                entity_id=c1.id,
            )
            db.add_all([li1, li2])
            await db.flush()
            print("[OK] Created list and list items")
        else:
            print("[SKIP] Lists already exist")

        # ---- Activity log (sample) ----
        result = await db.execute(select(ActivityLog).where(ActivityLog.tenant_id == tid).limit(1))
        if result.scalar_one_or_none() is None and candidates and roles:
            act = ActivityLog(
                tenant_id=tid,
                candidate_id=cand1.id,
                role_id=r1.id,
                type="NOTE",
                message="Initial screening call completed. Candidate interested. Scheduling technical round.",
                created_by="admin@test.com",
            )
            db.add(act)
            await db.flush()
            print("[OK] Created activity log entry")
        else:
            print("[SKIP] Activity log already has data")

        await db.commit()
        print()
        print("=" * 60)
        print("DEMO DATA SEED COMPLETE")
        print("=" * 60)
        print(f"Tenant ID: {tid}")
        print("Login at /login and browse Dashboard, Candidates, Companies,")
        print("Roles, Contacts, BD Opportunities, Tasks, Lists.")
        print("=" * 60)


if __name__ == "__main__":
    print("Seeding demo data...\n")
    asyncio.run(seed_demo_data())
    print("\n[OK] Done.")
