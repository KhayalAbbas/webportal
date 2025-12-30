"""
System diagnostics UI route.

Provides a browser-accessible diagnostics page for non-technical users
to verify the system is working correctly.
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.ui.dependencies import get_current_ui_user_and_tenant, UIUser
from app.db.session import get_db
from app.services.company_research_service import CompanyResearchService
from app.schemas.company_research import (
    CompanyResearchRunCreate,
    CompanyProspectCreate,
)

router = APIRouter(tags=["ui-system-check"])
templates = Jinja2Templates(directory="app/ui/templates")


async def run_diagnostic_checks(db: AsyncSession, tenant_id: str, role_id: str = None):
    """Run all diagnostic checks and return results."""
    checks = []
    
    # 1. Check company_research_runs table exists
    try:
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'company_research_runs'
            );
        """))
        exists = result.scalar()
        checks.append({
            "name": "Table 'company_research_runs' exists",
            "status": "pass" if exists else "fail",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "Table 'company_research_runs' exists",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # 2. Check company_prospects table exists
    try:
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'company_prospects'
            );
        """))
        exists = result.scalar()
        checks.append({
            "name": "Table 'company_prospects' exists",
            "status": "pass" if exists else "fail",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "Table 'company_prospects' exists",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # 3. Check required columns in company_research_runs
    required_run_columns = ["role_mandate_id", "status", "sector", "region_scope", 
                           "config", "tenant_id", "created_at", "name", "description"]
    try:
        result = await db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'company_research_runs'
        """))
        existing_columns = [row[0] for row in result.fetchall()]
        missing = [col for col in required_run_columns if col not in existing_columns]
        
        checks.append({
            "name": f"Required columns in 'company_research_runs' ({len(required_run_columns)} total)",
            "status": "pass" if len(missing) == 0 else "fail",
            "details": f"Missing: {', '.join(missing)}" if missing else "All present",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "Required columns in 'company_research_runs'",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # 4. Check required columns in company_prospects
    required_prospect_columns = ["company_research_run_id", "name_raw", "name_normalized",
                                "relevance_score", "evidence_score", "manual_priority", 
                                "is_pinned", "status", "tenant_id"]
    try:
        result = await db.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'company_prospects'
        """))
        existing_columns = [row[0] for row in result.fetchall()]
        missing = [col for col in required_prospect_columns if col not in existing_columns]
        
        checks.append({
            "name": f"Required columns in 'company_prospects' ({len(required_prospect_columns)} total)",
            "status": "pass" if len(missing) == 0 else "fail",
            "details": f"Missing: {', '.join(missing)}" if missing else "All present",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "Required columns in 'company_prospects'",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # 5. Functional test: Can create a run
    if role_id:
        try:
            service = CompanyResearchService(db)
            test_run = CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name="[DIAGNOSTIC TEST] Quick Check",
                description="Automated diagnostic test",
                sector="test",
                region_scope=["US"],
                status="planned",
            )
            
            run = await service.create_research_run(
                tenant_id=tenant_id,
                data=test_run,
            )
            
            # Clean up immediately
            await db.execute(text("DELETE FROM company_research_runs WHERE id = :id"), {"id": run.id})
            await db.commit()
            
            checks.append({
                "name": "Can create research run (service layer)",
                "status": "pass",
                "details": "Created and cleaned up test run",
                "category": "functional"
            })
        except Exception as e:
            checks.append({
                "name": "Can create research run (service layer)",
                "status": "fail",
                "error": str(e),
                "category": "functional"
            })
    else:
        checks.append({
            "name": "Can create research run (service layer)",
            "status": "skip",
            "details": "No role available for testing",
            "category": "functional"
        })
    
    # ========== PHASE 2A CHECKS: SOURCE-DRIVEN DISCOVERY ==========
    
    # Check source_documents table exists
    try:
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'source_documents'
            );
        """))
        exists = result.scalar()
        checks.append({
            "name": "[Phase 2A] Table 'source_documents' exists",
            "status": "pass" if exists else "fail",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "[Phase 2A] Table 'source_documents' exists",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # Check research_events table exists
    try:
        result = await db.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'research_events'
            );
        """))
        exists = result.scalar()
        checks.append({
            "name": "[Phase 2A] Table 'research_events' exists",
            "status": "pass" if exists else "fail",
            "category": "schema"
        })
    except Exception as e:
        checks.append({
            "name": "[Phase 2A] Table 'research_events' exists",
            "status": "fail",
            "error": str(e),
            "category": "schema"
        })
    
    # Functional: Can add source and extract companies
    if role_id:
        try:
            service = CompanyResearchService(db)
            from app.schemas.company_research import SourceDocumentCreate
            from app.services.company_extraction_service import CompanyExtractionService
            from uuid import uuid4
            
            # Create a test run
            test_run = CompanyResearchRunCreate(
                role_mandate_id=role_id,
                name="[SYSTEM CHECK Phase 2A] Test",
                description="Testing source extraction",
                status="active",
                sector="technology",
            )
            run = await service.create_research_run(tenant_id=tenant_id, data=test_run)
            
            # Add a text source
            source = await service.add_source(
                tenant_id=tenant_id,
                data=SourceDocumentCreate(
                    company_research_run_id=run.id,
                    source_type="text",
                    title="Test source",
                    content_text="Acme Corporation Inc is a test company. Beta Technologies Ltd is another.",
                )
            )
            
            checks.append({
                "name": "[Phase 2A] Can add source document",
                "status": "pass",
                "details": f"Added text source with ID {source.id}",
                "category": "functional"
            })
            
            # Test extraction
            extraction_service = CompanyExtractionService(db)
            result = await extraction_service.process_sources(
                tenant_id=tenant_id,
                run_id=run.id,
            )
            await db.commit()
            
            if result['processed'] >= 1:
                checks.append({
                    "name": "[Phase 2A] Can process sources",
                    "status": "pass",
                    "details": f"Processed {result['processed']} sources, found {result['companies_found']} companies",
                    "category": "functional"
                })
            else:
                checks.append({
                    "name": "[Phase 2A] Can process sources",
                    "status": "fail",
                    "error": "No sources were processed",
                    "category": "functional"
                })
            
            # Check if extraction found companies
            if result['companies_found'] >= 1:
                checks.append({
                    "name": "[Phase 2A] Company extraction works",
                    "status": "pass",
                    "details": f"Extracted {result['companies_found']} company names",
                    "category": "functional"
                })
            else:
                checks.append({
                    "name": "[Phase 2A] Company extraction works",
                    "status": "warn",
                    "details": "No companies extracted (extraction may need tuning)",
                    "category": "functional"
                })
            
            # Clean up
            await db.execute(text("DELETE FROM company_research_runs WHERE id = :id"), {"id": run.id})
            await db.commit()
            
        except Exception as e:
            checks.append({
                "name": "[Phase 2A] Source processing functional test",
                "status": "fail",
                "error": str(e),
                "category": "functional"
            })
    else:
        checks.append({
            "name": "[Phase 2A] Source processing functional test",
            "status": "skip",
            "details": "No role available for testing",
            "category": "functional"
        })
    
    return checks


@router.get("/ui/system-check", response_class=HTMLResponse)
async def system_check_page(
    request: Request,
    current_user: UIUser = Depends(get_current_ui_user_and_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    System diagnostics page - shows health checks for Company Research module.
    """
    # Get a test role if available
    result = await db.execute(text("""
        SELECT id FROM role 
        WHERE tenant_id = :tenant_id 
        LIMIT 1
    """), {"tenant_id": current_user.tenant_id})
    role_row = result.fetchone()
    test_role_id = role_row[0] if role_row else None
    
    # Run checks
    checks = await run_diagnostic_checks(db, current_user.tenant_id, test_role_id)
    
    # Calculate summary
    total = len(checks)
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    skipped = sum(1 for c in checks if c["status"] == "skip")
    
    overall_status = "pass" if failed == 0 else "fail"
    
    return templates.TemplateResponse(
        "system_check.html",
        {
            "request": request,
            "current_user": current_user,
            "active_page": "system_check",
            "checks": checks,
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "overall_status": overall_status,
        }
    )
