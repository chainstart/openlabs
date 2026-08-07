from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_llzto_novelty_audit_preserves_narrow_claim_boundary():
    audit = json.loads(
        (
            ROOT
            / "analysis/literature/llzto_novelty_audit_2026-08-07.json"
        ).read_text()
    )
    sources = audit["sources"]
    assert audit["search_as_of"] == "2026-08-07"
    assert len(sources) >= 14
    assert len({row["source_id"] for row in sources}) == len(sources)
    assert all(row["identifier"] and row["url"].startswith("https://") for row in sources)
    assert audit["decision"]["candidate_claim_survives_search"] is True
    assert audit["decision"]["survival_is_conditional"] is True
    assert audit["decision"]["external_refresh_required_at_submission"] is True
    prohibited = " ".join(audit["decision"]["prohibited_novelty_claims"])
    assert "first MLMD" in prohibited
    assert "diffusion strings" in prohibited
    assert audit["decision"]["journal_quartile_not_assessed_before_complete_results"]
