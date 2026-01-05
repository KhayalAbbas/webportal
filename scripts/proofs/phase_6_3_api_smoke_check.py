import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from httpx import ASGITransport, AsyncClient  # type: ignore

from app.core.dependencies import verify_user_tenant_access
from app.db.session import get_async_session_context
from app.main import app
from app.schemas.company_research import (
    CompanyProspectCreate,
    CompanyProspectEvidenceCreate,
    CompanyResearchRunCreate,
    SourceDocumentCreate,
)
from app.services.canonical_company_service import CanonicalCompanyService
from app.services.company_research_service import CompanyResearchService

TENANT_ID = str(uuid.uuid4())
ROLE_MANDATE_ID = UUID("45a00716-0fec-4de7-9ccf-26f14eb5f5fb")
TEST_DOMAIN = "phase63-smoke.example.com"

ARTIFACT_DIR = ROOT / "scripts" / "proofs" / "_artifacts"
CONSOLE = ARTIFACT_DIR / "phase_6_3_api_smoke_console.txt"
RESPONSES_JSON = ARTIFACT_DIR / "phase_6_3_api_smoke.json"


class DummyUser:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id


def override_verify_user() -> DummyUser:
    return DummyUser(TENANT_ID)


app.dependency_overrides[verify_user_tenant_access] = override_verify_user


def log(line: str) -> None:
    print(line)


async def seed_canonical_company() -> Dict[str, Any]:
    async with get_async_session_context() as session:
        service = CompanyResearchService(session)
        run = await service.create_research_run(
            tenant_id=TENANT_ID,
            data=CompanyResearchRunCreate(
                role_mandate_id=ROLE_MANDATE_ID,
                name=f"phase6_3_smoke_{uuid.uuid4().hex[:6]}",
                description="Phase 6.3 API smoke",
                sector="demo",
                region_scope=["US"],
                status="active",
            ),
        )

        source = await service.add_source(
            TENANT_ID,
            SourceDocumentCreate(
                company_research_run_id=run.id,
                source_type="text",
                title="Smoke proof source",
                content_text="Phase 6.3 smoke source for canonical companies",
                meta={"kind": "text", "label": "smoke"},
            ),
        )

        prospect = await service.create_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectCreate(
                company_research_run_id=run.id,
                role_mandate_id=ROLE_MANDATE_ID,
                name_raw="SmokeCo",
                name_normalized="smokeco",
                website_url=f"https://{TEST_DOMAIN}",
                hq_country="US",
                sector="demo",
                subsector="proof",
                employees_band="50-100",
                revenue_band_usd="1-5m",
                description="Smoke company",
                data_confidence=0.9,
                relevance_score=0.9,
                evidence_score=0.9,
                status="new",
                discovered_by="internal",
                verification_status="unverified",
                exec_search_enabled=True,
            ),
        )

        await service.add_evidence_to_prospect(
            tenant_id=TENANT_ID,
            data=CompanyProspectEvidenceCreate(
                tenant_id=UUID(TENANT_ID),
                company_prospect_id=prospect.id,
                source_type="text",
                source_name="smoke_evidence",
                source_url=source.url or f"https://{TEST_DOMAIN}/source",
                raw_snippet="Smoke evidence",
                evidence_weight=0.8,
                source_document_id=source.id,
                source_content_hash=source.content_hash,
            ),
        )

        await service.start_run(tenant_id=TENANT_ID, run_id=run.id)

        resolver = CanonicalCompanyService(session)
        summary = await resolver.resolve_run_companies(tenant_id=TENANT_ID, run_id=run.id)

        canonical = await service.repo.get_canonical_company_by_domain(TENANT_ID, TEST_DOMAIN)
        assert canonical, "canonical company not created"

        return {
            "run_id": str(run.id),
            "source_id": str(source.id),
            "prospect_id": str(prospect.id),
            "canonical_id": str(canonical.id),
            "resolver_summary": summary,
        }


def assert_endpoints(openapi_json: dict) -> None:
    required = {
        "/company-research/canonical-companies": "get",
        "/company-research/canonical-companies/{canonical_company_id}": "get",
        "/company-research/canonical-company-links": "get",
    }
    for path, method in required.items():
        assert path in openapi_json.get("paths", {}), f"missing path {path}"
        assert method.lower() in openapi_json["paths"][path], f"missing method {method} for {path}"


async def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_JSON.unlink(missing_ok=True)

    log("=== Phase 6.3 API smoke check ===")

    seeded = await seed_canonical_company()
    log(f"Seeded tenant {TENANT_ID} run {seeded['run_id']}")

    headers = {"X-Tenant-ID": TENANT_ID}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        openapi_resp = await client.get("/openapi.json")
        assert openapi_resp.status_code == 200, f"openapi status {openapi_resp.status_code}"
        openapi_json = openapi_resp.json()
        assert_endpoints(openapi_json)
        log("OpenAPI contains canonical company endpoints")

        list_resp = await client.get("/company-research/canonical-companies", headers=headers)
        assert list_resp.status_code == 200, f"list status {list_resp.status_code}"
        list_json = list_resp.json()
        assert isinstance(list_json, list) and len(list_json) >= 1, "list empty"
        first = list_json[0]
        for key in ["id", "canonical_name", "primary_domain", "linked_entities_count"]:
            assert key in first, f"missing {key} in list item"
        log("List endpoint returned canonical companies")

        canonical_id = first["id"]

        detail_resp = await client.get(f"/company-research/canonical-companies/{canonical_id}", headers=headers)
        assert detail_resp.status_code == 200, f"detail status {detail_resp.status_code}"
        detail_json = detail_resp.json()
        for key in ["id", "canonical_name", "domains", "links"]:
            assert key in detail_json, f"missing {key} in detail"
        assert detail_json.get("domains"), "domains empty"
        assert detail_json.get("links"), "links empty"
        log("Detail endpoint returned domains and links")

        links_resp = await client.get(
            f"/company-research/canonical-company-links?canonical_company_id={canonical_id}",
            headers=headers,
        )
        assert links_resp.status_code == 200, f"links status {links_resp.status_code}"
        links_json = links_resp.json()
        assert isinstance(links_json, list) and len(links_json) >= 1, "links empty"
        for link in links_json:
            for key in ["canonical_company_id", "company_entity_id", "evidence_source_document_id"]:
                assert key in link, f"missing {key} in link"
        log("Link endpoint returned evidence-bearing links")

    payload = {
        "openapi_status": 200,
        "endpoints_present": ["list", "detail", "links"],
        "seed": seeded,
        "list": list_json,
        "detail": detail_json,
        "links": links_json,
    }
    RESPONSES_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log(f"Wrote responses -> {RESPONSES_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
        log("PASS: Phase 6.3 API smoke check")
    except Exception as exc:  # pragma: no cover - proof diagnostics
        log(f"FAIL: {exc}")
        raise
