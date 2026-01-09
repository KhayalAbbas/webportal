"""Phase 11.4 proof: Google search cache + GCC region decomposition (mock-only).

Steps performed:
- Forces google_cse provider into fixture mode (ATS_MOCK_EXTERNAL_PROVIDERS=1).
- Clears prior cache + cache documents for the tenant.
- Runs google_cse once (miss) then again (hit) to prove cache reuse.
- Runs GCC region bundle twice to show cached UAE reuse + full region hits on second pass.
- Writes artifacts under scripts/proofs/_artifacts for verification.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.role import Role  # noqa: E402
from app.models.source_document import SourceDocument  # noqa: E402
from app.models.tenant_search_cache import TenantSearchCache  # noqa: E402
from app.schemas.company_research import CompanyResearchRunCreate  # noqa: E402
from app.services.company_research_service import CompanyResearchService  # noqa: E402
from app.repositories.search_cache_repository import SearchCacheRepository  # noqa: E402

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

PROOF_JSON = ARTIFACT_DIR / "phase_11_4_search_cache_proof.json"
PROOF_TXT = ARTIFACT_DIR / "phase_11_4_search_cache_proof.txt"


async def _get_default_role(session):
    result = await session.execute(select(Role).limit(1))
    return result.scalar_one_or_none()


async def _create_run(session, tenant_id: str, role_id: UUID):
    service = CompanyResearchService(session)
    run = await service.create_research_run(
        tenant_id=tenant_id,
        data=CompanyResearchRunCreate(
            role_mandate_id=role_id,
            name="Phase 11.4 Search Cache",
            description="Proof harness run",
            sector="Testing",
            region_scope=["GCC"],
            status="planned",
        ),
        created_by_user_id=None,
    )
    await session.commit()
    return run


async def _clear_cache(session, tenant_id: UUID) -> dict[str, int]:
    cache_repo = SearchCacheRepository(session)
    cache_deleted = await cache_repo.delete_by_provider(tenant_id=tenant_id, provider="google_cse")
    docs_deleted = 0
    cache_doc_ids: list[UUID] = []
    existing_docs = (
        await session.execute(
            select(SourceDocument).where(SourceDocument.tenant_id == tenant_id)
        )
    ).scalars().all()
    for doc in existing_docs:
        meta = doc.doc_metadata or {}
        if meta.get("kind") == "search_cache":
            cache_doc_ids.append(doc.id)
    if cache_doc_ids:
        await session.execute(delete(SourceDocument).where(SourceDocument.id.in_(cache_doc_ids)))
        docs_deleted = len(cache_doc_ids)
    await session.flush()
    return {"cache_rows": cache_deleted, "docs": docs_deleted}


async def _snapshot(session, tenant_id: UUID) -> dict[str, Any]:
    cache_rows = (
        await session.execute(
            select(TenantSearchCache).where(TenantSearchCache.tenant_id == tenant_id)
        )
    ).scalars().all()
    cache_docs = (
        await session.execute(
            select(SourceDocument).where(SourceDocument.tenant_id == tenant_id)
        )
    ).scalars().all()
    doc_payloads = []
    for doc in cache_docs:
        meta = doc.doc_metadata or {}
        if meta.get("kind") != "search_cache":
            continue
        doc_payloads.append(
            {
                "id": str(doc.id),
                "content_hash": doc.content_hash,
                "metadata": meta,
            }
        )
    return {
        "cache_entries": [
            {
                "id": str(row.id),
                "provider": row.provider,
                "cache_key": row.cache_key,
                "request_hash": row.request_hash,
                "expires_at": row.expires_at.isoformat(),
                "content_hash": row.content_hash,
                "source_document_id": str(row.source_document_id) if row.source_document_id else None,
            }
            for row in sorted(cache_rows, key=lambda r: r.cache_key)
        ],
        "cache_docs": sorted(doc_payloads, key=lambda d: d["id"]),
        "counts": {
            "cache_rows": len(cache_rows),
            "cache_docs": len(doc_payloads),
        },
    }


def _seed_env():
    os.environ["ATS_MOCK_EXTERNAL_PROVIDERS"] = "1"
    os.environ["GOOGLE_CSE_API_KEY"] = os.environ.get("GOOGLE_CSE_API_KEY") or "offline-api-key"
    os.environ["GOOGLE_CSE_CX"] = os.environ.get("GOOGLE_CSE_CX") or "offline-cx"
    settings.ATS_MOCK_EXTERNAL_PROVIDERS = True
    settings.GOOGLE_CSE_API_KEY = os.environ["GOOGLE_CSE_API_KEY"]
    settings.GOOGLE_CSE_CX = os.environ["GOOGLE_CSE_CX"]


async def main():
    _seed_env()

    async with AsyncSessionLocal() as session:
        role = await _get_default_role(session)
        if not role:
            raise RuntimeError("No role found to seed run")
        tenant_uuid = role.tenant_id
        tenant_id = str(tenant_uuid)

        cleared = await _clear_cache(session, tenant_uuid)
        await session.commit()

        run = await _create_run(session, tenant_id, role.id)
        service = CompanyResearchService(session)

        base_payload = {"query": "gcc renewable energy", "num_results": 2, "country": "AE"}
        first = await service.run_discovery_provider(tenant_id=tenant_id, run_id=run.id, provider_key="google_cse", request_payload=base_payload)
        second = await service.run_discovery_provider(tenant_id=tenant_id, run_id=run.id, provider_key="google_cse", request_payload=base_payload)

        region_first = await service.run_google_cse_region_bundle(
            tenant_id=tenant_id,
            run_id=run.id,
            query="gcc renewable energy",
            region="GCC",
            num_results=2,
        )
        region_second = await service.run_google_cse_region_bundle(
            tenant_id=tenant_id,
            run_id=run.id,
            query="gcc renewable energy",
            region="GCC",
            num_results=2,
        )

        snapshot = await _snapshot(session, tenant_uuid)
        await session.commit()

    proof = {
        "cleared": cleared,
        "first_call": first,
        "second_call": second,
        "region_first": region_first,
        "region_second": region_second,
        "snapshot": snapshot,
    }

    PROOF_JSON.write_text(json.dumps(proof, indent=2), encoding="utf-8")
    PROOF_TXT.write_text(
        "\n".join(
            [
                "Phase 11.4 search cache proof",
                f"Cleared cache rows={cleared['cache_rows']} docs={cleared['docs']}",
                f"First call cache_status={first.get('cache_status')} source_id={first.get('source_id')}",
                f"Second call cache_status={second.get('cache_status')} source_id={second.get('source_id')}",
                f"Region first statuses={[r.get('cache_status') for r in region_first.get('results', [])]}",
                f"Region second statuses={[r.get('cache_status') for r in region_second.get('results', [])]}",
                f"Cache entries={snapshot['counts']['cache_rows']} docs={snapshot['counts']['cache_docs']}",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
