import json
import re
from pathlib import Path

BASE = Path("scripts/proofs/_artifacts")
ASSERT_PATH = BASE / "phase_9_7_verify_close_assertions.txt"

UI_HTML = (BASE / "phase_9_7_verify_ui_html_excerpt.html").read_text(encoding="utf-8")
MARK_REQ = json.loads((BASE / "phase_9_7_verify_mark_same_request.json").read_text(encoding="utf-8"))
KEEP_REQ = json.loads((BASE / "phase_9_7_verify_keep_separate_request.json").read_text(encoding="utf-8"))
DB_TEXT = (BASE / "phase_9_7_verify_db_excerpt.txt").read_text(encoding="utf-8")
COMPARE_BEFORE = json.loads((BASE / "phase_9_7_verify_compare.json").read_text(encoding="utf-8"))
COMPARE_AFTER = json.loads((BASE / "phase_9_7_verify_compare_after.json").read_text(encoding="utf-8"))
CONSOLE = (BASE / "phase_9_7_verify_console.txt").read_text(encoding="utf-8")

results: list[str] = []
pass_all = True


def note(ok: bool, label: str, detail: str) -> None:
    global pass_all
    status = "PASS" if ok else "FAIL"
    results.append(f"[{status}] {label}: {detail}")
    if not ok:
        pass_all = False


def extract_ids() -> tuple[str | None, str | None]:
    run_match = re.search(r"run_id=([0-9a-f-]{36})", CONSOLE, re.IGNORECASE)
    prospect_match = re.search(r"prospect_id=([0-9a-f-]{36})", CONSOLE, re.IGNORECASE)
    run_id = run_match.group(1) if run_match else None
    prospect_id = prospect_match.group(1) if prospect_match else None
    return run_id, prospect_id


run_id, prospect_id = extract_ids()
note(run_id is not None, "console run_id", f"found run_id={run_id}")
note(prospect_id is not None, "console prospect_id", f"found prospect_id={prospect_id}")

# Assertion A: UI excerpt
if run_id and prospect_id:
    has_context = run_id in UI_HTML and prospect_id in UI_HTML
    note(has_context, "UI company context", "run_id/prospect_id present in compare panel html")
    endpoint_pattern = f"/company-research/runs/{run_id}/executives-compare"
    has_endpoint = endpoint_pattern in UI_HTML and prospect_id in UI_HTML
    note(has_endpoint, "UI compare endpoint", f"endpoint with context present ({endpoint_pattern})")
else:
    note(False, "UI company context", "run_id or prospect_id missing; cannot verify")
    note(False, "UI compare endpoint", "run_id or prospect_id missing; cannot verify")

# Assertion B: MARK_SAME request
mark_ids = bool(MARK_REQ.get("left_executive_id")) and bool(MARK_REQ.get("right_executive_id"))
mark_ev = bool(MARK_REQ.get("evidence_source_document_ids"))
note(mark_ids, "mark_same identifiers", f"left/right present={mark_ids}")
note(mark_ev, "mark_same evidence", f"evidence ids count={len(MARK_REQ.get('evidence_source_document_ids') or [])}")

# Assertion C: KEEP_SEPARATE request
keep_ids = bool(KEEP_REQ.get("left_executive_id")) and bool(KEEP_REQ.get("right_executive_id"))
keep_ev = bool(KEEP_REQ.get("evidence_source_document_ids"))
note(keep_ids, "keep_separate identifiers", f"left/right present={keep_ids}")
note(keep_ev, "keep_separate evidence", f"evidence ids count={len(KEEP_REQ.get('evidence_source_document_ids') or [])}")

# Assertion D: DB excerpt
lines = [line for line in DB_TEXT.splitlines() if line.strip()]
try:
    act_idx = lines.index("Activity log entries:")
except ValueError:
    act_idx = len(lines)
    note(False, "db layout", "Activity log entries header missing")

decision_lines = lines[1:act_idx]
activity_lines = lines[act_idx + 1 :] if act_idx < len(lines) else []

mark_seen = False
keep_seen = False
mark_ev_present = False
keep_ev_present = False
for line in decision_lines:
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        continue
    dtype = row.get("decision_type")
    ev = row.get("evidence_source_document_ids") or []
    if dtype == "mark_same":
        mark_seen = True
        mark_ev_present = mark_ev_present or bool(ev)
    if dtype == "keep_separate":
        keep_seen = True
        keep_ev_present = keep_ev_present or bool(ev)
note(mark_seen, "db mark_same row", "mark_same decision persisted")
note(keep_seen, "db keep_separate row", "keep_separate decision persisted")
note(mark_ev_present, "db mark_same evidence", "mark_same evidence pointers present")
note(keep_ev_present, "db keep_separate evidence", "keep_separate evidence pointers present")

activity_mark = any("decision=mark_same" in line for line in activity_lines)
activity_keep = any("decision=keep_separate" in line for line in activity_lines)
note(activity_mark, "activity mark_same", "ActivityLog entry for mark_same present")
note(activity_keep, "activity keep_separate", "ActivityLog entry for keep_separate present")

# Assertion E: Compare before/after
before_matches = len(COMPARE_BEFORE.get("candidate_matches") or [])
after_matches = len(COMPARE_AFTER.get("candidate_matches") or [])
note(before_matches >= 1, "compare before", f"candidate_matches={before_matches}")
note(after_matches < before_matches, "compare after", f"candidate_matches={after_matches} (before={before_matches})")

summary = "OVERALL PASS" if pass_all else "OVERALL FAIL"
results.append(summary)
ASSERT_PATH.write_text("\n".join(results), encoding="utf-8")
