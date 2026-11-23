"""Convergence fixes from the 2026-11-23 audit (maintenance/20261123-polish/audit-convergence).

Owner standard: data and conclusions must be true, correct and valid; imprecise wording is not
worth another round, but real numeric, formula and citation errors still block. Cases are built
from tonight's archived reviews (NEM five-minute settlement, PFAS, TIC 421871796, Campylobacter).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from paper_writing import formal_checks as formal
from paper_writing import resynthesis
from paper_writing import review_flow as flow
from paper_writing import review_round_guard as guard

# --- 1. minimum-change discipline in the round guard ---------------------------------------

NEM_R2 = ("\\documentclass{article}\\begin{document}\\title{Five-minute settlement}\n\\section{Methods}\n"
          "A fixed schedule earns the same under both rules whenever its net power is constant within each "
          "half-hour. The ratio of the two margins is reported for each window.\n\\end{document}\n")
# R3: the author's rewrite turned a sufficient condition into "only ..." and a universal bound.
NEM_R3 = NEM_R2.replace(
    "A fixed schedule earns the same under both rules whenever its net power is constant within each half-hour.",
    "More generally, only a schedule whose net power is constant within every half-hour earns the same "
    "under both rules.").replace(
    "The ratio of the two margins is reported for each window.",
    "Since the ratio cannot fall below one, the premium is the evidence.")


def test_undeclared_strengthening_is_held_by_the_guard():
    found = {row["family"] for row in guard.strengthening_additions(NEM_R2, NEM_R3)}
    assert {"only", "never"} <= found
    blockers = guard.revision_scope_blockers(NEM_R2, NEM_R3, None, ["item"], 20)
    assert len([b for b in blockers if b.startswith("Undeclared strengthening")]) == 2


def test_declared_new_text_passes_and_hedges_do_not_count():
    raw = json.dumps({"new_text": ["only a schedule whose net power is constant within every half-hour",
                                   "Since the ratio cannot fall below one"]})
    assert guard.revision_scope_blockers(NEM_R2, NEM_R3, raw, ["item"], 20) == []
    hedged = NEM_R2.replace("reported for each window.",
                            "reported for each window; it does not establish a mechanism and is not causal.")
    assert guard.strengthening_additions(NEM_R2, hedged) == []


def test_title_change_and_polish_rewrite_are_held_in_a_revision_round():
    retitled = NEM_R2.replace("\\title{Five-minute settlement}", "\\title{Spotted settlement premium}")
    assert any("title changed" in b for b in guard.revision_scope_blockers(NEM_R2, retitled, None, [], 0))
    long_old = NEM_R2.replace("\\end{document}", "word " * 1000 + "\\end{document}")
    blockers = guard.revision_scope_blockers(long_old, long_old, None, ["item"], 400)
    assert any("separate rounds" in b for b in blockers)
    assert guard.revision_scope_blockers(long_old, long_old, None, [], 400) == []


def test_guard_hold_for_scope_uses_no_round(tmp_path):
    snapshot = tmp_path / "manuscript-expanded.tex"
    snapshot.write_text(NEM_R2)
    last = {"_path": tmp_path / "decision.json", "round_evidence_files": {}, "figure_files": []}
    result = guard.check(tmp_path, "p", "J", last, {"expanded": NEM_R3}, {}, {}, None, [], {},
                         "d" * 64, None, datetime.now(UTC), guard.settings({}))
    assert any(b.startswith("Undeclared strengthening") for b in result["blockers"])
    # A guard hold never reaches the referees, so it records no scientific round.
    assert "consumes_scientific_round" not in result


# --- 2. follow-up synthesis ------------------------------------------------------------------

ITEM = "[evidence] Report the 95% interval of the ratio. (Results)"
CHANGED = flow.followup_changed_text(
    "+++ current\n+More generally, only a schedule whose net power is constant within every half-hour earns the same.\n")


def _report(recommendation="accept", findings=(), resolved=True):
    return {"recommendation": recommendation, "decision": "send_to_review", "dimension_repairs": {},
            "previous_items": [{"item": ITEM, "resolved": resolved, "evidence": "Done." if resolved else "Open.",
                                "reader_misconclusion": "" if resolved else "A reader would misread it."}],
            "new_findings": list(findings)}


def _finding(kind, text, location="§2.2"):
    return {"kind": kind, "location": location, "finding": text, "reader_misconclusion": "Wrong reading.",
            "why_missed": "The sentence is new."}


def _merge(editor, referees, changed=CHANGED):
    return flow.merge(editor, referees, [], formal_blockers=[], formal_summary=None, followup_items=[ITEM],
                      changed_text=changed)


INSIDE = _finding("unsupported_claim", "“only a schedule whose net power is constant” states a false converse.")
OUTSIDE = _finding("unsupported_claim", "“the premium rewards flexible dispatch” overstates the evidence.")
NUMBER = _finding("numeric_or_statistical_error", "The table reports 0.152 but the text says 0.1.", "Table 2")


def test_new_soft_finding_outside_the_changes_is_advice():
    merged = _merge(_report(), {"referee_a": _report("major_revision", [OUTSIDE]), "referee_b": _report()})
    assert merged["outcome"] == "ready"
    assert any(a.get("downgrade_reason") == "outside_changed_region" for a in merged["advisory_items"])


def test_new_soft_finding_inside_the_changes_blocks_with_minor_revision():
    merged = _merge(_report(), {"referee_a": _report("major_revision", [INSIDE]), "referee_b": _report()})
    assert merged["outcome"] == "revision_required"
    assert (merged["recommendation"], merged["next_action"]) == ("minor_revision", "text_revision")


def test_unsupported_claim_is_advice_when_referees_accept():
    merged = _merge(_report(), {"referee_a": _report("minor_revision", [INSIDE]), "referee_b": _report()})
    assert merged["outcome"] == "ready"


def test_numeric_error_blocks_anywhere_and_drives_major_revision():
    merged = _merge(_report(), {"referee_a": _report("accept", [NUMBER]), "referee_b": _report()},
                    changed=flow.followup_changed_text("+unrelated\n"))
    assert merged["outcome"] == "revision_required"
    assert (merged["recommendation"], merged["next_action"]) == ("major_revision", "evidence_remediation")


def test_same_item_from_three_roles_is_one_blocker():
    editor = _report(findings=[INSIDE], resolved=False)
    referees = {"referee_a": _report("major_revision", [INSIDE], resolved=False),
                "referee_b": _report("major_revision", [INSIDE], resolved=False)}
    merged = _merge(editor, referees)
    blocking = [c for c in merged["required_changes"] if not c["advisory"]]
    assert len(blocking) == 1 and blocking[0]["also_raised_by"] == ["referee_a", "referee_b"]
    assert len(merged["unresolved_previous_items"]) == 1
    assert merged["unresolved_previous_items"][0]["also_raised_by"] == ["referee_a", "referee_b"]


def test_older_records_without_change_text_keep_their_judgment():
    merged = _merge(_report(), {"referee_a": _report("major_revision", [OUTSIDE]), "referee_b": _report()},
                    changed=None)
    assert merged["outcome"] == "revision_required"


# --- 3. targeted formal follow-up -------------------------------------------------------------

def test_incomplete_followup_rechecks_only_what_failed(tmp_path, monkeypatch):
    import test_formal_checks as fixtures

    metadata = fixtures.fixture_workspace(tmp_path)
    fixtures.mock_http(monkeypatch)
    tex = tmp_path / metadata["manuscript_dir"] / "main.tex"
    tex.write_text(tex.read_text().replace(r"\end{document}",
                                           "Alpha prose.\n\nBeta prose.\n\nGamma prose.\n\n" + r"\end{document}"))
    runs = [tmp_path / f"run-{i}" for i in range(2)]
    for run in runs:
        run.mkdir()
    first = formal.run_checks({"metadata": metadata}, tmp_path, runs[0], fixtures.ROLE, 1, fixtures.simulated_runner)
    tex.write_text(tex.read_text().replace("Alpha prose.", "Alpha prose, revised."))
    second = formal.run_checks({"metadata": metadata, "previous_formal_check": first},
                               tmp_path, runs[1], fixtures.ROLE, 1, fixtures.simulated_runner)
    # Make the follow-up incomplete: one batch failed on the "Beta" passage.
    path = tmp_path / second["path"]
    report = json.loads(path.read_text())
    beta = next(p["id"] for p in report["inventory"]["passages"] + [
        p for p in formal.inventory(*formal.current_inputs(metadata, tmp_path))["passages"]] if "Beta" in p["text"])
    report["issue_summary"]["raw_findings"].append(
        {"category": "technical", "root": "", "location": "", "message": f"batch timed out for {beta}",
         "aggregate": False, "reason": "timeout", "status": None})
    path.write_text(json.dumps(report))
    binding = dict(second, sha256=formal.sha(path.read_bytes()))
    documents, bibliography = formal.current_inputs(metadata, tmp_path)
    targeted = formal._followup_inventory(binding, metadata, tmp_path, fixtures.ROLE, documents, bibliography)
    widened = formal._followup_inventory(binding, metadata, tmp_path, fixtures.ROLE, documents, bibliography,
                                         targeted=False)
    texts = [p["text"] for p in targeted["passages"]]
    assert [t for t in texts if "prose" in t] == ["Beta prose."]
    assert not any("real" in t for t in texts)
    assert targeted["scope"]["name"] == formal.TARGETED_FOLLOWUP_SCOPE
    assert widened["scope"]["name"] == formal.FOLLOWUP_SCOPE  # archived reports keep their own scope


def test_source_plan_change_names_only_the_affected_keys():
    prior = {"sources": [{"url": "https://a.example/x", "reference_keys": ["a"], "kind": "primary_text"},
                         {"url": "https://b.example/y", "reference_keys": ["b"], "kind": "primary_text"}]}
    metadata = {"formal_check": {"sources": [
        {"url": "https://a.example/x", "reference_keys": ["a"], "kind": "primary_text"},
        {"url": "https://b.example/new", "reference_keys": ["b"], "kind": "primary_text"}]}}
    assert formal._source_plan_changes(prior, metadata) == {"b"}


# --- 4. stall and final ruling -----------------------------------------------------------------

def _round(count, recs=("minor_revision", "minor_revision")):
    return {"merged": {"outcome": "revision_required",
                       "required_changes": [{"change": f"c{i}", "advisory": False} for i in range(count)],
                       "referee_recommendations": dict(zip(("referee_a", "referee_b"), recs))}}


def test_stall_when_blockers_do_not_fall_and_final_ruling_splits_items():
    merged = {"outcome": "revision_required", "recommendation": "minor_revision", "next_action": "text_revision",
              "scientific_blockers": [], "unresolved_previous_items": [], "dimension_repairs": {},
              "required_changes": [
                  {"type": "narrative", "change": "Say 'collected little'.", "location": "§4", "advisory": False,
                   "kind": "unsupported_claim"},
                  {"type": "evidence", "change": "0.152 is printed as 0.1.", "location": "Table 2",
                   "advisory": False, "kind": "numeric_or_statistical_error"}]}
    referees = {"referee_a": {"recommendation": "accept"}, "referee_b": {"recommendation": "minor_revision"}}
    basis = flow.stall_basis([_round(1), _round(2)], referees, merged, None)
    assert basis and basis["criterion"] == "blocking_count_not_falling"
    ruled = flow.apply_final_ruling(merged, basis)
    assert ruled["outcome"] == "revision_required"
    assert ruled["final_ruling"]["must_fix"] == ["[evidence] 0.152 is printed as 0.1. (Table 2)"]
    assert ruled["final_ruling"]["advice"] == ["Say 'collected little'."]
    # The next round tracks only the must-fix item.
    assert flow.previous_tracked_items({"merged": ruled}) == ["[evidence] 0.152 is printed as 0.1. (Table 2)"]


def test_final_ruling_without_must_fix_is_ready():
    merged = {"outcome": "revision_required", "scientific_blockers": [], "unresolved_previous_items": [],
              "dimension_repairs": {"readability": [{"repair": "Tighten §3."}]},
              "required_changes": [{"type": "narrative", "change": "Tighten §3.", "location": "readability",
                                    "advisory": False}]}
    ruled = flow.apply_final_ruling(merged, {"criterion": "rounds_after_accepting_referees"})
    assert ruled["outcome"] == "ready" and ruled["final_ruling"]["must_fix"] == []


def test_rounds_after_accepting_referees_and_new_not_below_resolved():
    referees = {"referee_a": {"recommendation": "accept"}, "referee_b": {"recommendation": "accept"}}
    merged = _round(1)["merged"]
    assert flow.stall_basis([_round(3, ("accept", "minor_revision")), _round(2, ("accept", "accept"))],
                            referees, merged, None)["criterion"] == "rounds_after_accepting_referees"
    merged = dict(_round(2)["merged"], unresolved_previous_items=[])
    basis = flow.stall_basis([_round(5, ("major_revision",) * 2)], referees, merged, ["a", "b"])
    assert basis["criterion"] == "new_blockers_not_below_resolved"


def test_final_check_admits_only_hard_new_findings():
    merged = flow.merge(_report(), {"referee_a": _report("major_revision", [INSIDE]), "referee_b": _report()},
                        [], formal_blockers=[], formal_summary=None, followup_items=[ITEM], changed_text=CHANGED,
                        final_check=True)
    assert merged["outcome"] == "ready"


# --- 5. policy hash, 6. preflight ---------------------------------------------------------------

def test_round_limit_grant_no_longer_changes_the_policy():
    config = {"process": "p", "roles": {}, "referee_roles": ["referee_a"], "rejection_clearance_required": True}
    grant = {"max_rounds_per_target": 20}
    assert flow.review_policy_sha256(config, None, grant) == flow.review_policy_sha256(config)


def test_preflight_rejects_duplicate_items_and_mismatched_schemas_before_any_call():
    schema = flow.referee_schema_for_previous({"items": ["a", "b"]})
    flow.preflight_review_schemas({"items": ["a", "b"]}, {"referee_a": schema})
    with pytest.raises(ValueError, match="duplicated"):
        flow.preflight_review_schemas({"items": ["a", "a"]}, {"referee_a": schema})
    with pytest.raises(ValueError, match="expects 2-2 previous items, not 3"):
        flow.preflight_review_schemas({"items": ["a", "b", "c"]}, {"referee_a": schema})
    # _previous_round already deduplicates, so a duplicate never reaches the models.
    assert list(dict.fromkeys(["a", "a", "b"])) == ["a", "b"]


# --- 7. delivery reader ---------------------------------------------------------------------------

def test_reader_avoids_referee_b_model():
    config = {"roles": {"referee_a": {"model": "claude-opus-5-5", "provider": "claude"},
                        "referee_b": {"model": "gpt-6.2-astra", "provider": "codex"},
                        "formal_verifier": {"model": "gpt-6.2-sol", "provider": "codex"}},
              "referee_roles": ["referee_a", "referee_b"]}
    role = flow.reader_role_config(config, flow.model_family("claude-opus-5-5", "claude"), "claude-opus-5-5")
    assert role["model"] == "gpt-6.2-sol"


def test_reader_cannot_block_when_referees_accept():
    merged = {"outcome": "ready", "required_changes": [], "referee_recommendations": {"referee_a": "accept"}}
    recall = {"repairs": [{"kind": "substantive", "repair": "Rename the axis.", "wrong_conclusion": "Misread.",
                           "why_missed": "New.", "previous_item": ""}],
              "question": "q", "comparison": "c", "answer": "a", "meaning": "m"}
    flow._merge_reader(merged, recall)
    assert merged["outcome"] == "ready" and merged["required_changes"][0]["advisory"]


# --- 9. resynthesis: one number set to its archived value ----------------------------------------

def test_number_replaced_by_archived_value_is_accepted(tmp_path):
    archive = tmp_path / "results.json"
    archive.write_text('{"max_shift": 0.152}')
    old = "\\section{Results}\nThe shift is at most 0.1 point.\n"
    new = "\\section{Results}\nThe shift is at most 0.152 point.\n"
    change = resynthesis.change_inventory(old, new)[0]
    row = dict(change, item="I", author_response="Matches the archive.", verification="results.json",
               archived_value={"path": "results.json", "sha256": flow._sha256(archive.read_bytes()),
                               "value": "0.152"})
    assert resynthesis._check_changes(old, new, {"changes": [row]}, {"I"}, tmp_path) == []
    bad = dict(row, archived_value=dict(row["archived_value"], value="0.153"))
    with pytest.raises(ValueError):
        resynthesis._check_changes(old, new, {"changes": [bad]}, {"I"}, tmp_path)
    plain = {k: v for k, v in row.items() if k != "archived_value"}
    with pytest.raises(ValueError, match="changes numeric results"):
        resynthesis._check_changes(old, new, {"changes": [plain]}, {"I"}, tmp_path)


# --- 12. source routing, 13. length -----------------------------------------------------------------

def test_missing_catalogue_url_is_checked_at_delivery_not_blocking():
    finding = {"category": "source_routing", "status": None,
               "message": "lucy1967: no queryable authoritative bibliographic evidence; register an official catalog URL"}
    assert formal.precision_finding(finding)
    assert not formal.precision_finding({"category": "scientific", "status": "error", "location": "L1",
                                         "message": "L1: error — 0.152 printed as 0.1"})


def test_small_length_request_is_advice():
    merged = {"outcome": "revision_required", "scientific_blockers": [], "unresolved_previous_items": [],
              "dimension_repairs": {"readability": [{"repair": "Shorten §4 by about 80 words."}]},
              "required_changes": [{"type": "narrative", "change": "Shorten §4 by about 80 words.",
                                    "location": "readability", "advisory": False}]}
    assert flow._length_requests_advice(merged)["outcome"] == "ready"
    assert not flow.length_request("Cut the sentence; it contradicts Table 2.")
