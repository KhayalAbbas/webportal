"""
Database health check utility.

Performs test queries to catch type mismatches and other DB issues early.
"""

from typing import Dict, List, Any
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.models.role import Role
from app.models.company import Company
from app.models.candidate import Candidate
from app.models.candidate_assignment import CandidateAssignment
from app.models.bd_opportunity import BDOpportunity
from app.models.task import Task
from app.models.tenant import Tenant


router = APIRouter()


async def run_health_checks(db: AsyncSession) -> Dict[str, Any]:
    """
    Run a series of database health checks.
    
    Returns a dict with check results and any errors encountered.
    """
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "checks": [],
        "overall_status": "healthy",
        "errors": []
    }
    
    # Check 1: Roles with candidate counts (dashboard query)
    try:
        roles_query = (
            select(
                Role,
                Company.name.label("company_name"),
                func.count(CandidateAssignment.id).label("candidate_count")
            )
            .join(Company, Company.id == Role.company_id)
            .outerjoin(CandidateAssignment, CandidateAssignment.role_id == Role.id)
            .group_by(Role.id, Company.name)
            .limit(5)
        )
        result = await db.execute(roles_query)
        roles = result.all()
        
        results["checks"].append({
            "name": "roles_with_candidates_join",
            "status": "pass",
            "message": f"Successfully queried {len(roles)} roles with candidate counts"
        })
    except Exception as e:
        results["overall_status"] = "unhealthy"
        results["errors"].append({
            "check": "roles_with_candidates_join",
            "error": str(e),
            "type": type(e).__name__
        })
        results["checks"].append({
            "name": "roles_with_candidates_join",
            "status": "fail",
            "message": str(e)
        })
    
    # Check 2: Candidates with assignments
    try:
        candidates_query = (
            select(Candidate)
            .limit(5)
        )
        result = await db.execute(candidates_query)
        candidates = result.scalars().all()
        
        results["checks"].append({
            "name": "candidates_query",
            "status": "pass",
            "message": f"Successfully queried {len(candidates)} candidates"
        })
    except Exception as e:
        results["overall_status"] = "unhealthy"
        results["errors"].append({
            "check": "candidates_query",
            "error": str(e),
            "type": type(e).__name__
        })
        results["checks"].append({
            "name": "candidates_query",
            "status": "fail",
            "message": str(e)
        })
    
    # Check 3: BD Opportunities with companies
    try:
        bd_query = (
            select(BDOpportunity, Company.name.label("company_name"))
            .join(Company, BDOpportunity.company_id == Company.id)
            .limit(5)
        )
        result = await db.execute(bd_query)
        opportunities = result.all()
        
        results["checks"].append({
            "name": "bd_opportunities_join",
            "status": "pass",
            "message": f"Successfully queried {len(opportunities)} BD opportunities"
        })
    except Exception as e:
        results["overall_status"] = "unhealthy"
        results["errors"].append({
            "check": "bd_opportunities_join",
            "error": str(e),
            "type": type(e).__name__
        })
        results["checks"].append({
            "name": "bd_opportunities_join",
            "status": "fail",
            "message": str(e)
        })
    
    # Check 4: Tasks query
    try:
        tasks_query = select(Task).limit(5)
        result = await db.execute(tasks_query)
        tasks = result.scalars().all()
        
        results["checks"].append({
            "name": "tasks_query",
            "status": "pass",
            "message": f"Successfully queried {len(tasks)} tasks"
        })
    except Exception as e:
        results["overall_status"] = "unhealthy"
        results["errors"].append({
            "check": "tasks_query",
            "error": str(e),
            "type": type(e).__name__
        })
        results["checks"].append({
            "name": "tasks_query",
            "status": "fail",
            "message": str(e)
        })
    
    # Check 5: Full-text search
    try:
        # Get a tenant to test with
        tenant_result = await db.execute(select(Tenant).limit(1))
        tenant = tenant_result.scalar_one_or_none()
        
        if tenant:
            from sqlalchemy import text
            search_query = text("""
                SELECT id, first_name, last_name
                FROM candidate
                WHERE tenant_id = :tenant_id
                AND search_vector @@ plainto_tsquery('english', 'test')
                LIMIT 3
            """)
            result = await db.execute(search_query, {"tenant_id": tenant.id})
            search_results = result.fetchall()
            
            results["checks"].append({
                "name": "full_text_search",
                "status": "pass",
                "message": f"Full-text search executed successfully ({len(search_results)} results)"
            })
        else:
            results["checks"].append({
                "name": "full_text_search",
                "status": "skip",
                "message": "No tenant found to test search"
            })
    except Exception as e:
        results["overall_status"] = "unhealthy"
        results["errors"].append({
            "check": "full_text_search",
            "error": str(e),
            "type": type(e).__name__
        })
        results["checks"].append({
            "name": "full_text_search",
            "status": "fail",
            "message": str(e)
        })
    
    return results


@router.get("/internal/db-health", response_class=HTMLResponse)
async def database_health_check(db: AsyncSession = Depends(get_db)):
    """
    Internal database health check endpoint.
    
    Runs test queries to verify database schema matches models.
    Returns HTML for browser viewing.
    """
    results = await run_health_checks(db)
    
    # Generate HTML response
    status_color = "#28a745" if results["overall_status"] == "healthy" else "#dc3545"
    status_emoji = "✅" if results["overall_status"] == "healthy" else "❌"
    
    checks_html = ""
    for check in results["checks"]:
        check_color = "#28a745" if check["status"] == "pass" else "#dc3545"
        check_emoji = "✅" if check["status"] == "pass" else "❌"
        checks_html += f"""
        <div style="padding: 10px; margin: 10px 0; background: #f8f9fa; border-left: 4px solid {check_color};">
            <strong>{check_emoji} {check['name']}</strong><br>
            <small>{check['message']}</small>
        </div>
        """
    
    errors_html = ""
    if results["errors"]:
        errors_html = "<h2>❌ Errors</h2>"
        for error in results["errors"]:
            errors_html += f"""
            <div style="padding: 10px; margin: 10px 0; background: #fff3cd; border-left: 4px solid #ffc107;">
                <strong>{error['check']}</strong><br>
                <code style="color: #dc3545;">{error['type']}: {error['error']}</code>
            </div>
            """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Database Health Check</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; max-width: 900px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: {status_color}; }}
            code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        </style>
    </head>
    <body>
        <h1>{status_emoji} Database Health: {results["overall_status"].upper()}</h1>
        <p><small>Checked at: {results["timestamp"]}</small></p>
        
        <h2>Checks</h2>
        {checks_html}
        
        {errors_html}
        
        <hr>
        <p><small>This is an internal diagnostic endpoint. Do not expose in production.</small></p>
    </body>
    </html>
    """
    
    status_code = 200 if results["overall_status"] == "healthy" else 500
    return HTMLResponse(content=html, status_code=status_code)


@router.get("/internal/db-health/json")
async def database_health_check_json(db: AsyncSession = Depends(get_db)):
    """
    Internal database health check endpoint (JSON format).
    
    Returns JSON for programmatic access.
    """
    results = await run_health_checks(db)
    status_code = 200 if results["overall_status"] == "healthy" else 500
    return JSONResponse(content=results, status_code=status_code)
