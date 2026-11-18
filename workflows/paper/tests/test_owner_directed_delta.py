"""Owner-directed limited revision without a new review (numbers added only)."""
import json
from pathlib import Path

import pytest

from paper_writing import review_flow as flow

P, T, V, BASIS = "p1", "Journal X", "1.2.3", "20261112T101031Z"
OLD = (r"\documentclass{article}\title{T}\begin{document}\begin{abstract}A\end{abstract}"
       "\n\\section{Introduction}\nIntro.\n\\section{Methods}\nWe used data.\n"
       "\\section{Results}\nThe share was 2.6 percent.\n\\section{Discussion}\nIt fell.\n\\end{document}\n")


def grant_metadata(root: Path, **overrides) -> dict:
    grant = {"kind": flow.OWNER_DIRECTED_DELTA_KIND, "paper_id": P, "target_journal": T,
             "manuscript_version": V, "basis_run_id": BASIS, "authorization": "Owner: add the figure; no re-review"}
    grant.update(overrides)
    receipt = {"schema": "openlabs.actual_author_instruction.v1", "source": "actual user message in this session",
               "user_text": "加图后不用重审", "authorizations": [grant]}
    path = root / "owner.json"
    path.write_text(json.dumps(receipt))
    return {"paper_id": P, "version": V, "target_journal": T,
            "owner_directed_delta": {"paper_id": P, "target_journal": T, "manuscript_version": V,
                                     "basis_run_id": BASIS,
                                     "authorization": {"path": "owner.json", "sha256": flow._sha256(path.read_bytes()),
                                                       "json_pointer": "/authorizations/0",
                                                       "summary": "Owner: add the figure; no re-review"}}}


def basis(root, monkeypatch, new_text, metadata):
    run = root / "reviews" / BASIS
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text(OLD)
    base = {"merged": {"outcome": "ready"}, "referee_reports": {"referee_a": {}}, "editor_screen": {"decision": "send_to_review"},
            "run_id": BASIS, "_path": run / "decision.json", "review_track": {"track": "routine"}}
    monkeypatch.setattr(flow, "scientific_rounds", lambda *a: [base])
    monkeypatch.setattr(flow, "review_policy_matches", lambda *a, **k: True)
    monkeypatch.setattr(flow, "rejection_context_blockers", lambda *a: [])
    config = {"referee_roles": ["referee_a"]}
    return flow.delta_review_basis(root, P, T, {"metadata": metadata, "expanded": new_text}, config,
                                   {"track": "routine"}, None, None)


ADDED = OLD.replace("We used data.", "We used data; the latest cycle was 2021--2023.")


def test_owner_grant_carries_over_added_numbers(tmp_path, monkeypatch):
    result = basis(tmp_path, monkeypatch, ADDED, grant_metadata(tmp_path))
    assert result["eligible"] is True and result["owner_directed"]["basis_run_id"] == BASIS
    assert result["owner_directed"]["numbers_added"]


def test_without_grant_added_numbers_need_full_review(tmp_path, monkeypatch):
    meta = grant_metadata(tmp_path); meta.pop("owner_directed_delta")
    result = basis(tmp_path, monkeypatch, ADDED, meta)
    assert result["eligible"] is False and any("numbers changed" in r for r in result["reasons"])


@pytest.mark.parametrize("new", [OLD.replace("2.6", "2.7"),                     # a number removed/changed
                                 OLD.replace("It fell.", "It fell sharply."),    # conclusion-bearing text
                                 OLD.replace("Intro.", "Intro 2026.")])          # introduction
def test_grant_does_not_cover_other_changes(tmp_path, monkeypatch, new):
    result = basis(tmp_path, monkeypatch, new, grant_metadata(tmp_path))
    assert result["eligible"] is False and "owner_directed" not in result


@pytest.mark.parametrize("override", [{"basis_run_id": "other"}, {"manuscript_version": "9.9"},
                                      {"paper_id": "other"}, {"kind": "other"}])
def test_grant_must_match_paper_version_and_basis(tmp_path, monkeypatch, override):
    meta = grant_metadata(tmp_path, **override)
    with pytest.raises(ValueError):
        basis(tmp_path, monkeypatch, ADDED, meta)


def test_changed_receipt_refuses(tmp_path, monkeypatch):
    meta = grant_metadata(tmp_path)
    (tmp_path / "owner.json").write_text("{}")
    with pytest.raises(ValueError, match="missing or changed"):
        basis(tmp_path, monkeypatch, ADDED, meta)


def test_ready_review_under_the_previous_panel_keeps_its_delta_basis(tmp_path, monkeypatch):
    """2026-11-18 model upgrade: a ready review made under the outgoing panel is still a basis."""
    old_roles = {"referee_a": {"model": "gpt-6-astra"}}
    run = tmp_path / "reviews" / BASIS
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text(OLD)
    base = {"merged": {"outcome": "ready"}, "referee_reports": {"referee_a": {}},
            "editor_screen": {"decision": "send_to_review"}, "run_id": BASIS, "_path": run / "decision.json",
            "review_track": {"track": "routine"}, "started_at": "2026-11-18T10:47:51+00:00",
            "active_referee_roles": ["referee_a"]}
    monkeypatch.setattr(flow, "scientific_rounds", lambda *a: [base])
    monkeypatch.setattr(flow, "review_policy_matches", lambda record, config, *a, **k: config["roles"] == old_roles)
    monkeypatch.setattr(flow, "rejection_context_blockers", lambda *a: [])
    config = {"referee_roles": ["referee_a"], "roles": {"referee_a": {"model": "gpt-6.2-astra"}},
              "previous_panels": [{"roles": old_roles, "referee_roles": ["referee_a"],
                                   "valid_for_reviews_started_before": "2026-11-18T13:46:00+00:00"}]}
    metadata = {"paper_id": P, "version": V, "target_journal": T}
    result = flow.delta_review_basis(tmp_path, P, T, {"metadata": metadata, "expanded": OLD}, config,
                                     {"track": "routine"}, None, None)
    assert not any("review policy changed" in reason for reason in result["reasons"])
    # Without the recorded earlier panel the same basis is refused.
    result = flow.delta_review_basis(tmp_path, P, T, {"metadata": metadata, "expanded": OLD},
                                     dict(config, previous_panels=[]), {"track": "routine"}, None, None)
    assert any("review policy changed" in reason for reason in result["reasons"])
