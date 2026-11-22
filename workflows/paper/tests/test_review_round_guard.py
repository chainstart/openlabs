"""A denied full review leaves the scientific round count and model calls unchanged."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from paper_writing import review_flow as flow
from test_review_flow import MANUSCRIPT, _delta_fixture, _round_response


@pytest.mark.parametrize("case, blocked_by", [
    ("missing_response", "Provide --response"),
    ("stale_response", "Provide --response"),
    ("omitted_figure", "Supply an evidence location"),
    ("only_wording", "Cite a new registered"),
    ("cooldown", None),
    ("override_wrong_target", None),
    ("override_empty_actor", "actor and reason"),
    ("old_artifact", "Cite a new registered"),
    ("old_job", "Cite a new registered"),
    ("unaddressed_analysis", "Cite a new registered"),
    ("invalid_location", "Supply valid evidence locations"),
    ("addressed", None),
    ("owner_override", None),
    ("legacy_addition", None),
])
def test_round_guard(tmp_path, monkeypatch, case, blocked_by):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace("standard design", "common design"))
    load_preflight = flow.preflight
    prior = next((tmp_path / "reviews/unified/p").glob("*/decision.json"))
    decision = json.loads(prior.read_text())
    finished = datetime.now(UTC) - timedelta(hours=4)
    if case in {"cooldown", "owner_override", "override_wrong_target", "override_empty_actor"}:
        finished = datetime.now(UTC) - timedelta(minutes=1)
    analysis = {"type": "evidence", "change": "External holdout is needed", "location": "Methods",
                "requires_new_artifact": True}
    figure = {"type": "figure", "change": "Label the axis", "location": "Figure 1"}
    decision.update(finished_at=finished.isoformat(),
                    merged={"outcome": "revision_required", "required_changes": [analysis, figure]})
    previous = tmp_path / "previous.csv"
    previous.write_text("rate\n0.5\n")
    new = tmp_path / "analysis.json"
    new.write_text('{"job_id": "holdout-2020", "rate": 0.75}')
    if case == "legacy_addition":
        from paper_writing.support import support_sources_digest
        decision.pop("round_evidence_files")
        decision["fingerprints"] = {"support_sources_sha256": support_sources_digest({"previous.csv": previous})}
    else:
        decision["round_evidence_files"] = {"previous.csv": flow._sha256(previous.read_bytes())}
    if case == "old_job":
        decision["round_evidence_jobs"] = {"old.json": "holdout-2020"}
    if case == "only_wording":
        decision["round_evidence_files"]["analysis.json"] = flow._sha256(new.read_bytes())
    prior.write_text(json.dumps(decision))
    manuscript = tmp_path / "main.tex"
    manuscript.write_text("See Figure 1 with the labeled axis.\n")
    pre = load_preflight()
    pre["metadata"]["support"] = {"publication": {"source_files": ["previous.csv", "analysis.json"]}}
    monkeypatch.setattr(flow, "preflight", lambda *args: pre)
    evidence = {"old_artifact": "sha256:" + flow._sha256(previous.read_bytes()),
                "legacy_addition": "sha256:" + flow._sha256(new.read_bytes())}.get(case, "job:holdout-2020")
    items = [
        {"item": flow.tracked_item(analysis), "status": "addressed",
         "explanation": "Computed rates on the independent holdout.", "evidence": [evidence]},
        {"item": flow.tracked_item(figure), "status": "addressed",
         "explanation": "Identified the plot axis.", "evidence": ["main.tex:1"]},
    ]
    if case == "omitted_figure":
        items[1]["evidence"] = []
    if case == "invalid_location":
        items[1]["evidence"] = ["main.tex:2"]
    if case == "unaddressed_analysis":
        items[0] |= {"status": "unaddressed", "explanation": "Holdout unavailable.", "evidence": []}
    response = _round_response(tmp_path, items)
    if case == "stale_response":
        response.write_text(json.dumps({"decision_sha256": "0" * 64, "items": items}))
    if case.startswith("override_") or case == "owner_override":
        config = flow.review_config(tmp_path)
        grant = {"paper_id": "p", "target_journal": "Other" if case.endswith("target") else "J",
                 "actor": "" if case.endswith("actor") else "Owner",
                 "reason": "Explicit early re-review", "decision_sha256": flow._sha256(prior.read_bytes())}
        if case == "override_empty_actor":
            with pytest.raises(ValueError, match=blocked_by):
                flow.review_round_guard.settings({"round_cooldown_overrides": [grant]})
            return
        config["round_guard"] = flow.review_round_guard.settings({"round_cooldown_overrides": [grant]})
    role = flow.run_role

    def respond(**kwargs):
        report, receipt = role(**kwargs)
        if kwargs["role_name"].startswith("referee"):
            report["previous_items"] = [
                {"item": row["item"], "resolved": True, "evidence": row["explanation"]}
                for row in items
            ]
        return report, receipt

    monkeypatch.setattr(flow, "run_role", respond)
    result = flow.run_review('p', root=tmp_path, response_letter=None if case == "missing_response" else response,
                             apply=False)
    rounds = flow.scientific_rounds(tmp_path, "p", "J")
    if blocked_by:
        assert result["merged"]["outcome"] == "review_round_blocked"
        assert any(blocked_by in reason for reason in result["round_guard"]["blockers"])
        assert not result["consumes_scientific_round"]
        assert calls == [] and len(rounds) == 1
        if case == "cooldown":
            assert result["round_guard"]["cooldown_only"] is True
    else:
        assert result["round_for_target"] == 2 and len(rounds) == 2
        assert "editor" in calls and "referee_a" in calls
        if case == "owner_override":
            assert result["round_guard"]["cooldown_override"] == grant


def test_parallel_review_does_not_start_a_second_pipeline(tmp_path, monkeypatch):
    def active_review(paper_id, *, root, **kwargs):
        return flow.run_review(paper_id, root=root, apply=False)

    monkeypatch.setattr(flow, "_run_review", active_review)
    result = flow.run_review("p", root=tmp_path, apply=False)
    assert result["merged"]["next_action"] == "wait"
    assert flow.scientific_rounds(tmp_path, "p", "J") == []


def test_no_required_items_needs_no_response(tmp_path):
    assert flow.review_round_guard.response_blockers(tmp_path, None, "previous", [], [], set(), set(), set(), set()) == []


def test_scientific_rebuttal_requires_verifiable_evidence(tmp_path):
    item = "Repeat the observation"
    (tmp_path / "methods.tex").write_text("The existing observation covers this interval.")
    row = {"item": item, "status": "rebutted", "explanation": "The interval is already covered."}
    def blockers(locations):
        raw = json.dumps({"items": [{**row, "evidence": locations}]})
        return flow.review_round_guard.response_blockers(tmp_path, raw, "previous", [item], [item],
                                                         set(), set(), set(), set())
    assert blockers([]) and not blockers(["methods.tex:1"])


def test_removing_evidence_is_a_change_for_the_referees(tmp_path):
    snapshot = tmp_path / "manuscript-expanded.tex"
    snapshot.write_text("Same text")
    last = {"_path": tmp_path / "decision.json", "round_evidence_files": {"old.csv": "old"},
            "figure_files": []}
    guard = flow.review_round_guard
    result = guard.check(tmp_path, "p", "J", last, {"expanded": snapshot.read_text()}, {}, {},
                         None, [], {}, "previous", None, datetime.now(UTC), guard.settings({}))
    assert result["blockers"] == [] and result["new_data"] == {}
