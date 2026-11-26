"""UD-20261126-review-pass-two-minor (user 2026-11-26): "2个评审，只要都是小修以上就过关".

With both referees at minor revision or better the paper passes; the editor, the delivery
reader and the referees' own items are advice, except a hard error (``materiality.hard_error``).
A referee at major revision or reject keeps the paper in revision only through its substantive
items.
"""
from __future__ import annotations

from paper_writing import materiality as m
from paper_writing import review_flow as flow


def finding(**fields):
    row = {"repair": "Restate the conclusion.", "kind": "unsupported_claim", "category": "body_claim",
           "reader_misconclusion": "A reader would take the effect as general.", "location": "Discussion, para 2",
           "in_changed_region": False, "requests": ["text_edit"], "why_missed": "", "previous_item": ""}
    row.update(fields)
    return row


def report(recommendation, **dims):
    return {"recommendation": recommendation, "previous_items": [], "scores": {"overall": 7},
            "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": [], **dims}}


def editor(**dims):
    return {"review_standard": "materiality_v1", "decision": "revise_before_submission",
            "desk_reject_category": "presentation",
            "dimension_repairs": {"science": [], "readability": [], "formal_accuracy": [], **dims}}


def reader(*repairs):
    return {"question": "q", "comparison": "c", "answer": "a", "meaning": "m", "repairs": list(repairs),
            "image_errors": []}


def blocking(merged):
    return [c for c in merged["required_changes"] if not c.get("advisory")]


def test_both_referees_minor_pass_even_if_the_editor_and_reader_want_revision():
    referees = {"referee_a": report("minor_revision", science=[finding()]),
                "referee_b": report("accept", readability=[finding(category="method_or_data")])}
    merged = flow.merge(editor(science=[finding(repair="Add a robustness check.", requests=["new_analysis"])]),
                        referees, reader_report=reader(finding(repair="Clarify the abstract.",
                                                               category="headline_claim", kind="advisory")))
    assert merged["outcome"] == "ready" and merged["next_action"] is None
    assert not blocking(merged)
    reasons = {c.get("downgrade_reason") for c in merged["required_changes"] if c.get("referee") != "delivery_reader"}
    assert "accepting_panel" in reasons and reasons <= {"accepting_panel", "accepting_readability"}


def test_referee_major_with_only_wording_items_passes():
    wording = [finding(category="wording", kind="advisory", reader_misconclusion=""),
               finding(category="style"), finding(category="definition_detail")]
    merged = flow.merge(editor(), {"referee_a": report("major_revision", readability=wording),
                                   "referee_b": report("minor_revision")})
    assert merged["outcome"] == "ready"


def test_referee_major_blocks_only_on_its_substantive_item():
    science = finding(repair="The pooled estimate does not support a causal reading; add the within-site test.",
                      category="method_or_data", requests=["new_analysis"])
    merged = flow.merge(editor(), {"referee_a": report("major_revision", science=[science],
                                                       readability=[finding(category="wording")]),
                                   "referee_b": report("minor_revision")})
    assert merged["outcome"] == "revision_required" and merged["next_action"] == "evidence_remediation"
    assert [c["change"] for c in blocking(merged)] == [science["repair"]]


def test_hard_errors_still_block_with_both_referees_at_minor():
    referees = {"referee_a": report("minor_revision"), "referee_b": report("accept")}
    for row in (finding(kind="numeric_or_statistical_error", category="figure_or_table"),
                finding(kind="figure_result_mismatch"), finding(kind="formula_error"),
                finding(kind="citation_nonexistent"), finding(kind="preregistration_violation")):
        merged = flow.merge(editor(science=[row]), referees)
        assert merged["outcome"] == "revision_required", row["kind"]
    # A headline claim the evidence does not support (claim-data mismatch) blocks too.
    headline = finding(category="headline_claim", location="Abstract")
    assert flow.merge(editor(), {"referee_a": report("minor_revision", science=[headline]),
                                 "referee_b": report("accept")})["outcome"] == "revision_required"
    # The delivery reader's own headline item stays advice.
    assert flow.merge(editor(), referees, reader_report=reader(headline))["outcome"] == "ready"


def test_formal_verifier_and_rejection_history_are_not_overridden():
    referees = {"referee_a": report("minor_revision"), "referee_b": report("accept")}
    formal = ["main:L10:abc: error — the stated bound is false"]
    merged = flow.merge(editor(), referees, formal_blockers=formal,
                        formal_summary={"by_category": {"scientific": formal}})
    assert merged["outcome"] == "formal_check_blocked"
    merged = flow.merge(editor(), referees, ["Prior editor: insufficient novelty remains unanswered"])
    assert merged["outcome"] == "rejection_history_blocked"


def test_followup_with_both_referees_accepting_drops_open_non_hard_items():
    item = "[evidence] Qualify the mechanism sentence."
    open_row = {"item": item, "resolved": False, "evidence": "The sentence is unchanged.",
                "reader_misconclusion": "A reader would take the mechanism as shown.",
                "kind": "unsupported_claim", "category": "body_claim", "requests": ["text_edit"]}
    resolved = dict(open_row, resolved=True, kind="advisory", requests=[])
    ed = {"review_standard": "materiality_v1", "decision": "send_to_review", "previous_items": [open_row],
          "new_findings": []}
    referees = {"referee_a": {"recommendation": "accept", "previous_items": [resolved], "new_findings": []},
                "referee_b": {"recommendation": "minor_revision", "previous_items": [open_row], "new_findings": []}}
    merged = flow.merge(ed, referees, followup_items=[item])
    assert merged["outcome"] == "ready"
    assert merged["unresolved_previous_items"][0]["downgrade_reason"] == "previous_accepting_panel"
    # A formal error tracked from the previous round is a hard error: it still blocks.
    error = "main:L667:5b6f58b465c9:F2: error — the variance formula is wrong"
    hard_row = dict(open_row, item=error, kind=None, category=None, requests=None)
    hard_row = {k: v for k, v in hard_row.items() if v is not None}
    ed["previous_items"] = [hard_row]
    referees["referee_b"]["previous_items"] = [hard_row]
    referees["referee_a"]["previous_items"] = [dict(hard_row, resolved=True)]
    assert flow.merge(ed, referees, followup_items=[error])["outcome"] == "revision_required"


def test_hard_error_list_is_narrow():
    assert m.HARD_KINDS == {"numeric_or_statistical_error", "formula_error", "figure_result_mismatch",
                            "preregistration_violation", "citation_nonexistent"}
    soft = m.normalize(finding(kind="citation_error_or_unsupported"), source="dimension", context=m.Context())
    assert not m.hard_error(soft)


def _reject_report(rec="reject", *, significance="Insufficient advance over prior work.", **dims):
    base = report(rec, **dims)
    base["scores"] = {"clarity": 6, "soundness": 5, "significance": 3, "novelty": 3, "overall": 3}
    base["significance"] = significance
    base["novelty_and_context"] = "Incremental over prior studies."
    return base


def test_both_reject_or_reject_and_major_without_items_route_to_direction_decision():
    ed = editor() | {"closest_prior_work": [{"work": "Lee 2023", "source": "reference_list",
                                             "known_result": "Same design"}]}
    # Both reject without concrete items: must route to direction_decision, never pass.
    both = flow.merge(ed, {"referee_a": _reject_report("reject"),
                           "referee_b": _reject_report("reject")})
    assert both["outcome"] == "revision_required"
    assert both["recommendation"] == "reject"
    assert both["next_action"] == "direction_decision"
    assert both["direction_context"]["trigger"] == "all_referees_reject"
    assert both["direction_context"]["options"] == list(flow.DIRECTION_OPTIONS)
    assert len(both["direction_context"]["referee_rejections"]) == 2
    assert flow.stall_basis([], {}, both, None) is None

    # Both reject WITH concrete items: still routes to direction_decision (same as old _merge_reports).
    substantive = finding(repair="Redo the identification.", category="method_or_data", requests=["new_analysis"])
    both_items = flow.merge(ed, {"referee_a": _reject_report("reject", science=[substantive]),
                                 "referee_b": _reject_report("reject")})
    assert both_items["outcome"] == "revision_required"
    assert both_items["next_action"] == "direction_decision"
    assert both_items["direction_context"]["trigger"] == "all_referees_reject"

    # One reject + one major_revision with NO concrete blocking items (or wording only): direction_decision.
    wording = [finding(category="wording", kind="advisory", reader_misconclusion="")]
    split_strict = flow.merge(ed, {"referee_a": _reject_report("reject", readability=wording),
                                   "referee_b": _reject_report("major_revision")})
    assert split_strict["outcome"] == "revision_required"
    assert split_strict["recommendation"] == "major_revision"
    assert split_strict["next_action"] == "direction_decision"
    assert split_strict["direction_context"]["trigger"] == "reject_and_major_without_items"
    assert {r["recommendation"] for r in split_strict["direction_context"]["referee_rejections"]} == {
        "reject", "major_revision"}

    # One reject + one major_revision WITH a concrete substantive item: normal revision_required.
    split_items = flow.merge(ed, {"referee_a": _reject_report("reject", science=[substantive]),
                                  "referee_b": _reject_report("major_revision")})
    assert split_items["outcome"] == "revision_required"
    assert split_items["next_action"] == "evidence_remediation"
    assert "direction_context" not in split_items

    # Same rule in the follow-up protocol when all previous items are resolved and no new findings remain.
    item = "[evidence] Add validation."
    resolved = {"item": item, "resolved": True, "evidence": "Done.", "reader_misconclusion": "",
                "kind": "advisory", "category": "body_claim", "requests": []}
    fu_ed = {"review_standard": "materiality_v1", "decision": "send_to_review",
             "previous_items": [resolved], "new_findings": []}
    for recs, expected_trigger in ((("reject", "reject"), "all_referees_reject"),
                                   (("reject", "major_revision"), "reject_and_major_without_items")):
        fu_refs = {
            "referee_a": {"recommendation": recs[0], "previous_items": [resolved], "new_findings": [],
                          "significance": "Core claim remains unconvincing.", "scores": {"significance": 3, "novelty": 3, "overall": 3}},
            "referee_b": {"recommendation": recs[1], "previous_items": [resolved], "new_findings": [],
                          "significance": "Advance is too thin.", "scores": {"significance": 4, "novelty": 4, "overall": 4}},
        }
        merged = flow.merge(fu_ed, fu_refs, followup_items=[item])
        assert merged["outcome"] == "revision_required"
        assert merged["next_action"] == "direction_decision"
        assert merged["direction_context"]["trigger"] == expected_trigger


def test_formal_technical_failure_does_not_block_accepting_panel_but_reports_needs_rerun():
    from paper_writing import formal_checks as fc

    referees = {"referee_a": report("accept"), "referee_b": report("minor_revision")}
    quote_err = "Quoted evidence is absent from source S1 at Crossref message.abstract"
    key_err = "Evidence does not bind every claimed reference key"
    raw = [
        {"category": "technical", "root": "main:L39:abc", "location": "main:L39:abc:C1:k",
         "message": quote_err, "aggregate": False, "reason": "", "status": None},
        {"category": "technical", "root": "main:L41:def", "location": "main:L41:def:C0:m",
         "message": key_err, "aggregate": False, "reason": "", "status": None},
    ]
    summary = fc.issue_summary(raw)

    # First-round materiality_v1: pure technical failure -> ready, reported as advice/needs-rerun.
    merged = flow.merge(editor(), referees, formal_blockers=[quote_err, key_err], formal_summary=summary)
    assert merged["outcome"] == "ready" and merged["next_action"] is None
    assert merged["formal_verifier_needs_rerun"] == [quote_err, key_err]
    assert merged["technical_blockers"] == []
    assert all(a["needs_rerun"] and a["downgrade_reason"] == "formal_accepting_technical"
               for a in merged["advisory_items"])

    # Follow-up protocol with by_category-only stage failure (e.g. missing evidence file / outage): ready.
    stage_err = "Mandatory core-verification stage failed: Formal evidence file is missing"
    stage_summary = {"by_category": {"scientific": [], "technical": [stage_err],
                                     "source_routing": [], "preparation": []}}
    fu_ed = {"review_standard": "materiality_v1", "decision": "send_to_review",
             "previous_items": [], "new_findings": []}
    fu_refs = {name: {"recommendation": rec, "previous_items": [], "new_findings": []}
               for name, rec in (("referee_a", "accept"), ("referee_b", "accept"))}
    fu_merged = flow.merge(fu_ed, fu_refs, formal_blockers=[stage_err],
                           formal_summary=stage_summary, followup_items=[])
    assert fu_merged["outcome"] == "ready" and fu_merged["next_action"] is None
    assert fu_merged["formal_verifier_needs_rerun"] == [stage_err]
    assert any(a.get("needs_rerun") and a["change"] == stage_err for a in fu_merged["advisory_items"])

    # Mixed technical + verified manuscript error: scientific error STILL blocks.
    sci_err = "main:L208:abc: error — the stated rate disagrees with Table 1"
    mixed = fc.issue_summary([
        *raw,
        {"category": "scientific", "root": "main:L208:abc", "location": "main:L208:abc",
         "message": sci_err, "aggregate": False, "reason": "wrong number", "status": "error"},
    ])
    blocked = flow.merge(editor(), referees, formal_blockers=[quote_err, sci_err], formal_summary=mixed)
    assert blocked["outcome"] == "formal_check_blocked"
    assert sci_err in blocked["scientific_blockers"]
    assert blocked["formal_verifier_needs_rerun"] == [quote_err]

    # Non-accepting panel (a referee at major_revision): technical failure still blocks.
    strict = flow.merge(editor(), {"referee_a": report("major_revision"), "referee_b": report("accept")},
                        formal_blockers=[quote_err], formal_summary=summary)
    assert strict["outcome"] == "formal_check_blocked"
    assert strict["technical_blockers"] == [quote_err, key_err]


def test_formal_technical_needs_rerun_passes_apply_and_release_validation(tmp_path, monkeypatch):
    import json
    from paper_writing import formal_checks as fc
    from test_formal_checks import ROLE, fixture_workspace, mock_http, simulated_runner

    metadata = fixture_workspace(tmp_path)
    metadata["target_journal"] = "J"
    mock_http(monkeypatch)
    run = tmp_path / "reviews/unified/p/20261126T000000Z"
    run.mkdir(parents=True)

    # Produce a real bound formal-check report whose ONLY blocker is a verifier technical quote slip.
    def misquoting_runner(**kw):
        out, receipt = simulated_runner(**kw)
        if out["references"]:
            out["references"][0]["evidence"][0]["quote"] = "paraphrased quote absent from source"
            workdir = kw["workdir"]
            raw_out = json.dumps(out, indent=2)
            (workdir / "output.json").write_text(raw_out)
            receipt["output_sha256"] = fc.sha(raw_out.encode())
            (workdir / "receipt.json").write_text(json.dumps(receipt, indent=2))
        return out, receipt

    binding = fc.run_checks({"metadata": metadata}, tmp_path, run, ROLE, 1, misquoting_runner)
    assert binding["valid"] is False
    assert binding["issue_summary"]["by_category"]["technical"]
    assert not binding["issue_summary"]["by_category"]["scientific"]

    # Strict validation fails, accepting validation passes, and a real scientific error still fails both.
    assert fc.validate_binding(binding, metadata, tmp_path, ROLE)
    assert fc.validate_binding(binding, metadata, tmp_path, ROLE, precision=True, accepting=True) == []

    # Wire into apply_decision + validate_unified_release + delivery_issues.
    config = {"process": flow.PROCESS,
              "roles": {"editor": ROLE, "referee_a": ROLE, "referee_b": dict(ROLE, model="other-model")},
              "referee_roles": ["referee_a", "referee_b"], "rejection_clearance_required": True,
              "max_rounds_per_target": 4, "previous_panels": []}
    monkeypatch.setattr(flow, "review_config", lambda root: config)
    written = []
    monkeypatch.setattr(flow, "load_paper_metadata", lambda *args: metadata)
    monkeypatch.setattr(flow, "write_paper_metadata", lambda pid, value, root: written.append(value))
    from paper_writing import operations
    monkeypatch.setattr(operations, "_review_workspace_fingerprints", lambda *args: {"manuscript_snapshot_sha256": "a" * 64})

    ed = editor() | {"decision": "send_to_review", "desk_reject_category": "none"}
    refs = {name: report("accept") | {"formal_check_assessment": {"coverage_complete": True, "omissions_or_errors": []}}
            for name in ("referee_a", "referee_b")}
    merged = flow.merge(ed, refs, formal_blockers=binding["blockers"], formal_summary=binding["issue_summary"])
    assert merged["outcome"] == "ready"
    record = {"paper_id": "p", "target_journal": metadata["target_journal"], "manuscript_version": str(metadata["version"]),
              "finished_at": "2026-11-26T00:00:00Z", "round_for_target": 1,
              "review_policy_sha256": flow.review_policy_sha256(config), "active_referee_roles": ["referee_a", "referee_b"],
              "prior_decisions": [], "editor_screen": ed, "referee_reports": refs, "merged": merged,
              "formal_check": binding, "formal_verifier_needs_rerun": merged["formal_verifier_needs_rerun"],
              "fingerprints": {"manuscript_snapshot_sha256": "a" * 64}}
    decision_path = run / "decision.json"
    digest = flow._json_dump(decision_path, record)
    release = flow.apply_decision("p", root=tmp_path, decision_path=decision_path, digest=digest)
    assert release["status"] == "ready"
    assert release["formal_verifier_needs_rerun"] == binding["blockers"]
    metadata["writing_release"] = release
    assert flow.validate_unified_release("p", metadata, tmp_path, "a" * 64) == []

    # Stage exception (no report file path) also passes validate_binding on an accepting panel,
    # while a fake non-technical empty summary is rejected.
    stage_binding = {"valid": False, "schema": fc.VERSION,
                     "issue_summary": {"by_category": {"scientific": [], "technical": ["stage outage"],
                                                       "source_routing": [], "preparation": []}}}
    assert fc.validate_binding(stage_binding, metadata, tmp_path, ROLE, precision=True, accepting=True) == []
    bad_binding = {"valid": False, "schema": fc.VERSION,
                   "issue_summary": {"by_category": {"scientific": ["real error"], "technical": ["stage outage"],
                                                     "source_routing": [], "preparation": []}}}
    assert fc.validate_binding(bad_binding, metadata, tmp_path, ROLE, precision=True, accepting=True)
