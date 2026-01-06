"""Capture OpenAPI after Phase 7.10 changes."""

import asyncio
import json
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from app.main import app

ARTIFACT_DIR = Path("scripts/proofs/_artifacts")
AFTER_JSON = ARTIFACT_DIR / "phase_7_10_openapi_after.json"
AFTER_EXCERPT = ARTIFACT_DIR / "phase_7_10_openapi_after_excerpt.txt"


def build_excerpt(data: dict) -> str:
    lines: list[str] = []
    paths = data.get("paths", {})
    targets = [
        "/company-research/runs/{run_id}/executives-compare",
        "/company-research/runs/{run_id}/executives-merge-decision",
        "/company-research/runs/{run_id}/executives",
    ]
    for path in targets:
        if path not in paths:
            lines.append(f"MISSING {path}")
            continue
        for method, op in paths[path].items():
            lines.append(f"{method.upper()} {path} summary={op.get('summary')}")
            for code, resp in (op.get("responses") or {}).items():
                desc = resp.get("description") or ""
                lines.append(f"  {code}: {desc}")
    schemas = data.get("components", {}).get("schemas", {})
    for name in ["ExecutiveCompareResponse", "ExecutiveCompareMatch", "ExecutiveMergeDecisionRequest", "ExecutiveMergeDecisionRead", "ExecutiveProspectRead"]:
        if name in schemas:
            keys = sorted(list((schemas[name].get("properties") or {}).keys()))
            lines.append(f"schema {name}: keys={keys}")
        else:
            lines.append(f"schema {name}: MISSING")
    return "\n".join(lines)


async def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/openapi.json")
        resp.raise_for_status()
        data = resp.json()
    AFTER_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    AFTER_EXCERPT.write_text(build_excerpt(data), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())