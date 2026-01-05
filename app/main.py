"""
Main FastAPI application.

This is the entry point for the API server.
"""

from fastapi import FastAPI
from contextlib import asynccontextmanager

from app.core.config import settings
from app.routers import (
    health,
    health_check,
    seed_info,
    auth,
    company,
    candidate,
    contact,
    role,
    candidate_assignment,
    bd_opportunity,
    task,
    lists,
    research_events,
    source_documents,
    ai_enrichments,
    enrichment_assignments,
    search,
    company_research,
    research_runs,
)

# UI routes
from app.ui.routes import (
    auth as ui_auth,
    dashboard,
    candidates as ui_candidates,
    roles as ui_roles,
    companies as ui_companies,
    contacts as ui_contacts,
    bd_opportunities as ui_bd_opportunities,
    tasks as ui_tasks,
    lists as ui_lists,
    research as ui_research,
    research_upload,
    company_research as ui_company_research,
    ai_proposal_routes as ui_ai_proposal,
    system_check,
    stubs,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for the FastAPI app.
    
    This runs code when the server starts and stops.
    - On startup: You could initialize connections, load models, etc.
    - On shutdown: You could close connections, cleanup resources, etc.
    """
    # Startup: runs when the server starts
    print(f"Starting {settings.APP_NAME}...")
    
    yield  # The server runs while we're "yielded" here
    
    # Shutdown: runs when the server stops
    print(f"Shutting down {settings.APP_NAME}...")


# Create the FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for SaaS ATS + Agentic Research Engine",
    version="0.1.0",
    lifespan=lifespan,
)


# Include routers (API endpoints)
app.include_router(health.router, tags=["Health"])
app.include_router(health_check.router, tags=["Internal"])
app.include_router(seed_info.router, tags=["Internal"])
app.include_router(auth.router)
app.include_router(company.router)
app.include_router(candidate.router)
app.include_router(contact.router)
app.include_router(role.router)
app.include_router(candidate_assignment.router)
app.include_router(bd_opportunity.router)
app.include_router(task.router)
app.include_router(lists.list_router)
app.include_router(lists.list_item_router)
app.include_router(research_events.router)
app.include_router(source_documents.router)
app.include_router(ai_enrichments.router)
app.include_router(enrichment_assignments.router)
app.include_router(search.router)
app.include_router(company_research.router)
app.include_router(research_runs.router)

# UI routes (session-based authentication)
app.include_router(ui_auth.router)
app.include_router(dashboard.router)
app.include_router(ui_candidates.router)
app.include_router(ui_roles.router)
app.include_router(ui_companies.router)
app.include_router(ui_contacts.router)
app.include_router(ui_bd_opportunities.router)
app.include_router(ui_tasks.router)
app.include_router(ui_lists.router)
app.include_router(ui_research.router)
app.include_router(research_upload.router)
app.include_router(ui_company_research.router)
app.include_router(ui_ai_proposal.router)
app.include_router(system_check.router)
app.include_router(stubs.router)


# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint - redirects to login or dashboard.
    """
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/login", status_code=303)
