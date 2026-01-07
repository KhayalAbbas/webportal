import asyncio
import json
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.main import app

AFTER = Path("scripts/proofs/_artifacts/phase_9_7_openapi_after.json")
EXCERPT = Path("scripts/proofs/_artifacts/phase_9_7_openapi_after_excerpt.txt")
TARGET_PATH_KEYS = [
    "executives-compare",
    "executives-merge-decision",
    "executive-discovery",
    "/company-research/runs",
]
SCHEMA_KEYWORDS = ["executive", "compare", "decision", "companyresearchrun"]


def should_keep_path(path: str) -> bool:
    return any(key in path for key in TARGET_PATH_KEYS)


def should_keep_schema(name: str) -> bool:
    lname = name.lower()
    return any(key in lname for key in SCHEMA_KEYWORDS)


async def main() -> None:
    AFTER.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.get("/openapi.json")
        resp.raise_for_status()
        data = resp.json()

    AFTER.write_text(json.dumps(data, indent=2), encoding="utf-8")

    lines: list[str] = []
    for path, methods in sorted((data.get("paths") or {}).items()):
        if not should_keep_path(path):
            continue
        lines.append(path)
        for method, detail in methods.items():
            summary = detail.get("summary") or ""
            lines.append(f"  {method.upper()}: {summary}")
            if "requestBody" in detail:
                lines.append("    requestBody: yes")
            responses = detail.get("responses") or {}
            if "200" in responses:
                desc = responses.get("200", {}).get("description") or ""
                lines.append(f"    200: {desc}")

    schemas = (data.get("components") or {}).get("schemas") or {}
    for name in sorted(schemas):
        if not should_keep_schema(name):
            continue
        props = schemas[name].get("properties") or {}
        lines.append(f"SCHEMA {name}")
        lines.append("  fields: " + ", ".join(sorted(props)))

    EXCERPT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
