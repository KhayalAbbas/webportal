import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))

from fastapi.testclient import TestClient  # type: ignore
from app.main import app

ARTIFACT_FULL = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_6_3_openapi_after_full.json"
ARTIFACT_SNIPPET = ROOT / "scripts" / "proofs" / "_artifacts" / "phase_6_3_openapi_after.txt"
ARTIFACT_FULL.parent.mkdir(parents=True, exist_ok=True)

client = TestClient(app)
response = client.get("/openapi.json")
assert response.status_code == 200, f"unexpected status {response.status_code}"

payload = response.json()
pretty = json.dumps(payload, indent=2, sort_keys=True)
ARTIFACT_FULL.write_text(pretty + "\n", encoding="utf-8")

lines = pretty.splitlines()
excerpt = "\n".join(lines[:250]) + "\n"
ARTIFACT_SNIPPET.write_text(excerpt, encoding="utf-8")

print(f"status {response.status_code}")
print(f"full -> {ARTIFACT_FULL.relative_to(ROOT)}")
print(f"excerpt lines={min(len(lines), 250)} -> {ARTIFACT_SNIPPET.relative_to(ROOT)}")
