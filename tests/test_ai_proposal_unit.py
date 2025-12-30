import json
from pathlib import Path

from app.schemas.ai_proposal import AIProposal


def load_sample():
    sample_path = Path(__file__).parent.parent / "sample_typed_metrics.json"
    with sample_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_ai_proposal_validation_and_metric_slugify():
    data = load_sample()

    proposal = AIProposal(**data)

    # Basic shape checks
    assert proposal.companies, "companies should not be empty"
    assert len(proposal.sources) == len({s.temp_id for s in proposal.sources}), "source temp_ids must be unique"

    # Metrics slugify: allow spaces/specials and ensure normalized keys
    for company in proposal.companies:
        for metric in company.metrics:
            assert metric.key == metric.key.strip(), "metric key should be normalized"
            assert " " not in metric.key
            assert "__" not in metric.key

    # Idempotent parse: repeated validation yields same normalized keys
    proposal_again = AIProposal(**data)
    assert [m.key for m in proposal.companies[0].metrics] == [m.key for m in proposal_again.companies[0].metrics]