import copy
import hashlib
import json
import os
import stat
import zipfile

import pytest

from paper_writing import review_flow as flow
from paper_writing.review_launcher import LaunchError, _validate_against_schema, role_runtime, run_role


def editor(decision="send_to_review", category="none"):
    return {"decision": decision, "desk_reject_category": category}


def test_separate_document_packet_includes_tables_and_supplement_once(tmp_path):
    man = tmp_path / "papers/p/manuscript"
    man.mkdir(parents=True)
    (man / "main.tex").write_text(r"\documentclass{article}\begin{document}MAIN\end{document}")
    for name, marker in [("table1.tex", "TABLE_CONTENT"), ("supplementary.tex", "SI_CONTENT")]:
        (man / name).write_text(r"\documentclass{article}\begin{document}" + marker + r"\end{document}")
    (man / "unreferenced-fragment.tex").write_text("NOT_A_DECLARED_DOCUMENT")
    expanded = flow.expanded_review_documents(man)
    assert expanded.count("TABLE_CONTENT") == expanded.count("SI_CONTENT") == 1
    assert "NOT_A_DECLARED_DOCUMENT" not in expanded
    pre = {"metadata": {"paper_id": "p"}, "expanded": expanded, "bibliography": "",
           "expanded_includes_standalone_documents": True}
    for packet in (flow.editor_packet(pre, []), flow.referee_packet(pre, tmp_path, None)):
        assert packet.count("TABLE_CONTENT") == packet.count("SI_CONTENT") == 1


def _active_revision_fixture(tmp_path):
    docs = []
    for kind, text in [('decision_letter', 'JBI-26-3391: invitation to revise, not acceptance.'),
                       ('reviewer_report', 'Reviewer 1: improve the reusable benchmark interface.')]:
        path = tmp_path / (kind + '.txt')
        path.write_text(text)
        docs.append({'kind': kind, 'path': path.name,
                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'target_journal': 'Journal',
            'submission_followup': {'journal': 'Journal', 'manuscript_number': 'JBI-26-3391'},
            'journal_revision_context': {'journal': 'Journal', 'manuscript_number': 'JBI-26-3391',
                                         'stage': 'revision_invited', 'documents': docs,
                                         'provenance': {'authenticated': True, 'source': 'original journal export'}}}


def test_ongoing_revision_originals_reach_editor_and_referee_without_becoming_rejections(tmp_path):
    meta = _active_revision_fixture(tmp_path)
    context = flow.active_revision_context(meta, tmp_path)
    pre = {'metadata': meta, 'expanded': 'Current manuscript', 'bibliography': 'References',
           'active_revision_context': context, 'author_response': 'Response: a method interface is supplied.'}
    for packet in [flow.editor_packet(pre, []), flow.referee_packet(pre, tmp_path, None)]:
        assert 'JBI-26-3391: invitation to revise, not acceptance.' in packet
        assert 'Reviewer 1: improve the reusable benchmark interface.' in packet
        assert 'does not establish acceptance' in packet
        assert 'Response: a method interface is supplied.' in packet
    assert flow.prior_decisions('p', meta, tmp_path) == []


@pytest.mark.parametrize('fault', ['changed', 'unsafe_path', 'mismatched_identity', 'inline_summary', 'internal_review'])
def test_ongoing_revision_rejects_unbound_or_wrong_originals(tmp_path, fault):
    meta = _active_revision_fixture(tmp_path)
    doc = meta['journal_revision_context']['documents'][0]
    if fault == 'changed':
        (tmp_path / doc['path']).write_text('altered invitation')
    elif fault == 'unsafe_path':
        doc['path'] = '../elsewhere.txt'
    elif fault == 'mismatched_identity':
        meta['journal_revision_context']['manuscript_number'] = 'another-paper'
    elif fault == 'inline_summary':
        doc['text'] = 'author summary replacing original'
    else:
        doc['path'] = 'reviews/internal-output.txt'
    with pytest.raises(ValueError):
        flow.active_revision_context(meta, tmp_path)


def test_ongoing_revision_requires_real_reports_and_has_no_default_context(tmp_path):
    assert flow.active_revision_context({}, tmp_path) is None
    meta = _active_revision_fixture(tmp_path)
    meta['journal_revision_context']['documents'].pop()
    with pytest.raises(ValueError, match='both the actual decision and reviewer report'):
        flow.active_revision_context(meta, tmp_path)


def referee(rec="minor_revision", blockers=(), changes=(), previous=()):
    return {"recommendation": rec, "scientific_blockers": list(blockers),
            "required_changes": [{"change": c, "type": t, "location": "S1"} for c, t in changes],
            "previous_items": list(previous), "scores": {"overall": 6},
            "formal_check_assessment": {"coverage_complete": True, "omissions_or_errors": []}}


def mock_formal_stage(monkeypatch):
    # These existing tests isolate rejection/round/panel behavior. The real
    # evidence stage and its integration failures are exercised separately.
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *args: {'valid': True, 'blockers': []})
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda *args: [])
    monkeypatch.setattr(flow.formal_checks, 'packet', lambda *args: 'Formal audit fixture')


@pytest.mark.parametrize("decision,category,action", [
    ("revise_before_submission", "presentation", "text_revision"),
    ("desk_reject", "presentation", "text_revision"),
    ("desk_reject", "scope", "retarget_required"),
    ("desk_reject", "readership", "retarget_required"),
    # Polishing cannot answer an insufficient advance: the orchestrator chooses a direction.
    ("desk_reject", "significance", "direction_decision"),
    ("desk_reject", "incremental", "direction_decision"),
    ("desk_reject", "novelty_unclear", "evidence_remediation"),
])
def test_editor_screen_stops_before_referees(decision, category, action):
    merged = flow.merge(editor(decision, category), {})
    assert merged["outcome"] == decision and merged["next_action"] == action


def test_unsubstantiated_stricter_recommendation_does_not_prevail():
    # The stricter referee listed no scientific blocker, evidence change or
    # main-claim narrowing, so the more favourable recommendation is used.
    merged = flow.merge(editor(), {"referee_a": referee("accept"), "referee_b": referee("major_revision")})
    assert merged["recommendation"] == "accept" and merged["outcome"] == "ready"
    assert merged["referee_recommendations"] == {"referee_a": "accept", "referee_b": "major_revision"}


def test_substantiated_stricter_recommendation_prevails():
    evidence = flow.merge(editor(), {"referee_a": referee("accept"),
                                     "referee_b": referee("major_revision", changes=[("add a baseline", "evidence")])})
    assert evidence["recommendation"] == "major_revision" and evidence["outcome"] == "revision_required"
    assert evidence["next_action"] == "evidence_remediation"
    blocked = flow.merge(editor(), {"referee_a": referee("reject", blockers=["Lemma 2 is false"]),
                                    "referee_b": referee("accept")})
    assert blocked["recommendation"] == "reject" and blocked["outcome"] == "revision_required"


def test_both_referees_strict_without_items_still_not_ready():
    merged = flow.merge(editor(), {"referee_a": referee("major_revision"), "referee_b": referee("reject")})
    assert merged["recommendation"] == "major_revision" and merged["outcome"] == "revision_required"


def test_significance_desk_reject_carries_direction_context():
    screen = editor("desk_reject", "significance") | {
        "strongest_desk_reject_reason": "Only a re-run of Smith (2024) on a new county sample.",
        "closest_prior_work": [{"work": "Smith 2024", "source": "reference_list", "known_result": "Same estimator"}],
        "advance_over_prior_work": "A new sample."}
    merged = flow.merge(screen, {})
    assert merged["next_action"] == "direction_decision"
    context = merged["direction_context"]
    assert context["strongest_desk_reject_reason"].startswith("Only a re-run")
    assert context["closest_prior_work"][0]["work"] == "Smith 2024"
    assert context["options"] == list(flow.DIRECTION_OPTIONS)
    assert "direction_context" not in flow.merge(editor("desk_reject", "scope"), {})


def test_editor_revision_requests_remain_mandatory_but_desk_suggestions_do_not():
    screen = editor("revise_before_submission", "presentation") | {"presentation_problems": ["Define the main object before the theorem."]}
    changes = flow.merge(screen, {})["required_changes"]
    assert changes[0]["type"] == "text" and changes[0]["referee"] == "editor"
    rejected = screen | {"decision": "desk_reject", "desk_reject_category": "significance"}
    assert flow.merge(rejected, {})["required_changes"] == []


def test_previous_editor_presentation_requests_are_not_tracked(tmp_path):
    # Editor presentation requests are text; they stay in the letter but are not
    # forced mandatory items, and no response letter is needed for them alone.
    run = tmp_path / "reviews/unified/example/20260101T000000Z"
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text("old text")
    record = {"stage_reached": "decision", "target_journal": "Journal", "merged": {"required_changes": []},
              "letter": "Please define X.",
              "editor_screen": {"decision": "revise_before_submission", "presentation_problems": ["Define X."]}}
    (run / "decision.json").write_text(json.dumps(record))
    previous = flow._previous_round(tmp_path, "example", "Journal", "new text", "X is now defined.")
    assert previous["items"] == [] and previous["letter"] == "Please define X."
    assert flow._previous_round(tmp_path, "example", "Journal", "new text", None)["items"] == []


def test_only_scientific_and_evidence_items_enter_next_round_tracking(tmp_path):
    run = tmp_path / "reviews/unified/example/20260101T000000Z"
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text("old text")
    changes = [{"type": "text", "change": "Fix the abstract tense", "location": "Abstract"},
               {"type": "evidence", "change": "Add a placebo test", "location": "Sec. 4", "main_claim": False},
               {"type": "claim_narrowing", "change": "Limit Fig. 3 wording", "location": "Sec. 5", "main_claim": False},
               {"type": "claim_narrowing", "change": "Narrow the headline effect", "location": "Abstract", "main_claim": True}]
    record = {"stage_reached": "decision", "target_journal": "Journal",
              "merged": {"scientific_blockers": ["Identification fails without the placebo"],
                         "required_changes": changes,
                         "unresolved_previous_items": [{"item": "[text] Old wording", "resolved": False},
                                                       {"item": "[evidence] Old robustness", "resolved": False}]},
              "editor_screen": {"decision": "send_to_review"}}
    (run / "decision.json").write_text(json.dumps(record))
    items = flow._previous_round(tmp_path, "example", "Journal", "new", "response")["items"]
    assert items == ["Identification fails without the placebo",
                     "[evidence] Add a placebo test (Sec. 4)",
                     "[claim_narrowing] Narrow the headline effect (Abstract)"]
    policy_items = flow.previous_tracked_items(record | {"merged": record["merged"]}, history_policy={})
    assert "[evidence] Old robustness" in policy_items and "[text] Old wording" not in policy_items
    with pytest.raises(ValueError, match="response letter"):
        flow._previous_round(tmp_path, "example", "Journal", "new", None)
    # The referee schema then constrains previous_items to exactly these items.
    schema = flow.referee_schema_for_previous({"items": items})["properties"]["previous_items"]
    assert schema["items"]["properties"]["item"]["enum"] == items


def test_ready_only_with_text_changes_and_no_blockers():
    ready = flow.merge(editor(), {"referee_a": referee("accept"),
                                  "referee_b": referee("minor_revision", changes=[("typo", "text")])})
    assert ready["outcome"] == "ready" and ready["next_action"] is None
    assert ready["required_changes"] == [{"change": "typo", "type": "text", "location": "S1",
                                          "referee": "referee_b", "advisory": True}]
    # A claim_narrowing without the main_claim field (older reports) still blocks.
    narrowing = flow.merge(editor(), {"referee_a": referee("accept"),
                                      "referee_b": referee("minor_revision", changes=[("weaken", "claim_narrowing")])})
    assert narrowing["outcome"] == "revision_required" and narrowing["next_action"] == "text_revision"
    blocked = flow.merge(editor(), {"referee_a": referee("accept", blockers=["gap in Lemma 2"]),
                                    "referee_b": referee("accept")})
    assert blocked["outcome"] == "revision_required" and blocked["next_action"] == "evidence_remediation"
    assert blocked["scientific_blockers"] == ["gap in Lemma 2"]


def test_text_only_requests_from_a_major_revision_referee_are_advisory():
    # Even a referee asking for many text changes cannot hold back a sound paper
    # when the other referee accepts and nobody reports a substantive item.
    text = [("tighten the introduction", "text"), ("abstract tense", "text")]
    merged = flow.merge(editor(), {"referee_a": referee("accept"),
                                   "referee_b": referee("major_revision", changes=text)})
    assert merged["outcome"] == "ready" and all(c["advisory"] for c in merged["required_changes"])


@pytest.mark.parametrize("main_claim,ready", [(False, True), (True, False)])
def test_claim_narrowing_blocks_only_for_main_claims(main_claim, ready):
    report = referee("minor_revision")
    report["required_changes"] = [{"change": "soften", "type": "claim_narrowing", "location": "Sec. 5",
                                   "main_claim": main_claim}]
    merged = flow.merge(editor(), {"referee_a": referee("accept"), "referee_b": report})
    assert (merged["outcome"] == "ready") is ready
    assert merged["required_changes"][0]["advisory"] is ready


def test_unresolved_previous_text_item_from_older_records_is_advisory():
    item = {"item": "[text] Fix the abstract tense (Abstract)", "resolved": False, "evidence": "still past tense"}
    merged = flow.merge(editor(), {"referee_a": referee("accept", previous=[item]), "referee_b": referee("accept")})
    assert merged["outcome"] == "ready" and merged["unresolved_previous_items"][0]["advisory"] is True


def test_unresolved_previous_item_blocks_ready():
    item = {"item": "fix intro", "resolved": False, "evidence": "only a disclaimer was added"}
    merged = flow.merge(editor(), {"referee_a": referee("accept", previous=[item]), "referee_b": referee("accept")})
    assert merged["outcome"] == "revision_required"


def test_only_numbered_previous_items_block_ready():
    optional = {"id": "running title", "item": "optional title", "resolved": False, "evidence": "unchanged"}
    numbered = {"id": "P1", "item": "fix intro", "resolved": False, "evidence": "unchanged"}
    ok = flow.merge(editor(), {"referee_a": referee("accept", previous=[optional]),
                               "referee_b": referee("accept")}, {"P1"})
    assert ok["outcome"] == "ready"
    blocked = flow.merge(editor(), {"referee_a": referee("accept", previous=[numbered]),
                                    "referee_b": referee("accept")}, {"P1"})
    assert blocked["outcome"] == "revision_required"


def test_legacy_paths_refuse_when_unified(monkeypatch):
    monkeypatch.setattr(flow, "unified_enabled", lambda root: True)
    with pytest.raises(ValueError, match="disabled"):
        flow.require_legacy_review_allowed("/nonexistent", "Legacy thing")
    monkeypatch.setattr(flow, "unified_enabled", lambda root: False)
    flow.require_legacy_review_allowed("/nonexistent", "Legacy thing")


def test_schema_validation_rejects_bad_records():
    with pytest.raises(LaunchError):
        _validate_against_schema({"decision": "maybe"}, {"type": "object", "properties": {
            "decision": {"type": "string", "enum": ["send_to_review"]}}})
    with pytest.raises(LaunchError):
        _validate_against_schema({"a": 1, "b": 2}, {"type": "object", "additionalProperties": False,
                                                      "properties": {"a": {"type": "integer"}}})
    with pytest.raises(LaunchError):
        _validate_against_schema(11, {"type": "integer", "minimum": 1, "maximum": 10})


def test_role_runtime_requires_known_provider_and_exact_model():
    assert role_runtime({"provider": "openai-codex", "tool": "Codex", "model": "gpt-6.1-sol"}) == "codex"
    with pytest.raises(LaunchError):
        role_runtime({"provider": "other", "tool": "X", "model": "m"})
    with pytest.raises(LaunchError):
        role_runtime({"provider": "anthropic", "tool": "Claude Code", "model": "bad model"})


def _fake_claude(tmp_path, monkeypatch, reported_model):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    payload = {"structured_output": {"answer": "ok"}, "modelUsage": {reported_model: {}}}
    script.write_text("#!/bin/sh\ncat >/dev/null\necho '" + json.dumps(payload) + "'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_launcher_records_reported_model_and_hashes(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, "claude-opus-5-5")
    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    result, receipt = run_role(role_name="editor", role={"provider": "anthropic", "tool": "Claude Code",
                                                         "model": "claude-opus-5-5"},
                               system_prompt="sys", user_prompt="hello", schema=schema, workdir=tmp_path / "run")
    assert result == {"answer": "ok"}
    assert receipt["runtime_reported_models"] == ["claude-opus-5-5"]
    assert receipt["prompt_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert receipt["tools_enabled"] is False and receipt["prior_scores_supplied"] is False


def test_launcher_rejects_model_substitution(tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, "some-other-model")
    with pytest.raises(LaunchError, match="reported models"):
        run_role(role_name="editor", role={"provider": "anthropic", "tool": "Claude Code", "model": "claude-opus-5-5"},
                 system_prompt="s", user_prompt="u", schema={"type": "object"}, workdir=tmp_path / "run")


def test_expand_and_front_matter(tmp_path):
    (tmp_path / "sec").mkdir()
    (tmp_path / "sec" / "intro.tex").write_text("\\section{Introduction}\nWe study X.\n"
                                               "\\begin{theorem}Every X is Y.\\end{theorem}\n\\section{Proof}\nP.\n")
    (tmp_path / "main.tex").write_text("\\title{On X}\n\\begin{abstract}Short.\\end{abstract}\n"
                                       "% \\input{ignored}\n\\input{sec/intro}\n")
    expanded = flow.expand_tex(tmp_path / "main.tex", tmp_path)
    parts = flow.front_matter(expanded)
    assert parts["title"] == "On X" and parts["abstract"] == "Short."
    assert "We study X." in parts["introduction"] and "Proof" not in parts["introduction"]
    assert "Every X is Y." in parts["main_statements"]


def test_editor_receives_complete_disclosure_and_actual_submitted_source(tmp_path, monkeypatch):
    monkeypatch.delenv('ARA_PAPER_MANAGE_API_URL', raising=False)
    old = tmp_path / 'submitted.tex'
    old.write_text('Old actual submitted theorem.\n')
    binding = {'journal':'J', 'manuscript_number':'123', 'path':'submitted.tex',
               'sha256':hashlib.sha256(old.read_bytes()).hexdigest(),
               'authenticated_submission_binding':True, 'package_id':'submitted-package'}
    metadata = {'journal_rejections':[{'journal':'J','manuscript_number':'123'}],
                'journal_submitted_versions':[binding]}
    decisions = flow.prior_decisions('p', metadata, tmp_path)
    expanded = (r'\title{Current}\begin{abstract}Abstract.\end{abstract}'
                '\n' + r'\section{Introduction}Intro.\section{Proof}Proof.'
                '\n' + r'\section{AI use}Current truthful disclosure.')
    packet = flow.editor_packet({'expanded':expanded,'metadata':metadata,'bibliography':''}, decisions)
    assert 'Current truthful disclosure.' in packet
    assert 'Old actual submitted theorem.' in packet
    assert 'submitted-package' in packet
    record = {'prior_decisions':decisions}
    assert not flow.rejection_context_blockers(record, metadata, tmp_path)
    old.write_text('Changed historical source.\n')
    assert any('submitted manuscript' in b for b in flow.rejection_context_blockers(record, metadata, tmp_path))
    with pytest.raises(ValueError, match='comparison source changed'):
        flow.prior_decisions('p', metadata, tmp_path)


def test_unbound_old_local_draft_is_not_submission_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv('ARA_PAPER_MANAGE_API_URL', raising=False)
    metadata = {'journal_rejections':[{'journal':'J','manuscript_number':'123'}],
                'journal_submitted_versions':[{'journal':'J','manuscript_number':'123',
                                               'path':'arbitrary.tex',
                                               'authenticated_submission_binding':False}]}
    assert 'submitted_manuscript' not in flow.prior_decisions('p', metadata, tmp_path)[0]


def _historical_report_metadata(tmp_path, monkeypatch):
    monkeypatch.delenv('ARA_PAPER_MANAGE_API_URL', raising=False)
    report = tmp_path / 'reports' / 'expert-1.txt'
    report.parent.mkdir()
    report.write_text('Expert 1: the earlier proof omits a joined-gadget distance bound.\n')
    document = {'journal': 'J', 'manuscript_number': '123', 'path': 'reports/expert-1.txt',
                'sha256': hashlib.sha256(report.read_bytes()).hexdigest(),
                'source_kind': 'authenticated_journal_expert_report', 'stage': 'pre_final',
                'provenance': {'authenticated': True, 'source': 'authenticated artifact download',
                               'artifact_id': 'actual-report-artifact'}}
    metadata = {'journal_rejections': [{'journal': 'J', 'manuscript_number': '123'}],
                'journal_prior_review_documents': [document]}
    return metadata, report


def test_exact_pre_final_reports_reach_both_roles_without_replacing_final_letter(tmp_path, monkeypatch):
    metadata, report = _historical_report_metadata(tmp_path, monkeypatch)
    decisions = flow.prior_decisions('p', metadata, tmp_path)
    supplied = decisions[0]['prior_review_documents'][0]
    assert supplied['text'] == report.read_text()
    assert supplied['sha256'] == hashlib.sha256(report.read_bytes()).hexdigest()
    assert supplied['provenance'] == metadata['journal_prior_review_documents'][0]['provenance']
    pre = {'metadata': metadata, 'expanded': r'\title{Current}\section{Introduction}Proof.',
           'bibliography': ''}
    for packet in (flow.editor_packet(pre, decisions), flow.referee_packet(pre, tmp_path, None, decisions)):
        assert 'the earlier proof omits a joined-gadget distance bound.' in packet
        assert 'actual-report-artifact' in packet and supplied['sha256'] in packet
        assert 'pre_final' in packet and 'not the final' in packet.replace('not final', 'not the final')
    assert decisions[0]['letter_available'] is False
    addressed = {'decision_id': decisions[0]['decision_id'], 'journal': 'J',
                 'judgment': 'resolved', 'answered': True, 'evidence': 'Current proof, Section 2'}
    assert any('Original rejection letter unavailable' in b for b in
               flow.rejection_clearance_blockers(editor() | {'prior_rejections_addressed': [addressed]}, decisions))


def test_official_run_supplies_authenticated_report_to_editor_and_active_referee(tmp_path, monkeypatch):
    mock_formal_stage(monkeypatch)
    metadata, report = _historical_report_metadata(tmp_path, monkeypatch)
    letter = tmp_path / 'letter.txt'
    letter.write_text('Final editor: the earlier expert concerns remained unresolved.\n')
    metadata['journal_rejection_letters'] = [{'journal': 'J', 'manuscript_number': '123',
        'path': 'letter.txt', 'kind': 'verbatim_decision_letter',
        'sha256': hashlib.sha256(letter.read_bytes()).hexdigest()}]
    metadata.update(version='1.0', target_journal='J')
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_b': {'provider': 'openai-codex'}}, 'referee_roles': ['referee_b'],
              'timeout_seconds': 1, 'max_rounds_per_target': 15, 'rejection_clearance_required': True}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    monkeypatch.setattr(flow, 'preflight', lambda *args: {
        'metadata': metadata, 'target': 'J', 'blockers': [], 'fingerprints': {},
        'expanded': r'\title{Current}\section{Introduction}The joined-gadget proof.', 'bibliography': ''})
    identity = flow.prior_decisions('p', metadata, tmp_path)[0]['decision_id']
    prompts = {}
    def role(**kwargs):
        name = kwargs['role_name']; prompts[name] = kwargs['user_prompt']
        if name == 'editor':
            return editor() | {'prior_rejections_addressed': [{'decision_id': identity, 'journal': 'J',
                'answered': True, 'judgment': 'resolved', 'evidence': 'Current joined-gadget proof'}]}, {}
        if name == 'decision_letter':
            return {'letter': 'Internal simulated decision'}, {}
        return referee('accept'), {}
    monkeypatch.setattr(flow, 'run_role', role)
    record = flow.run_review('p', root=tmp_path, apply=False)
    for name in ('editor', 'referee_b'):
        assert report.read_text().strip() in prompts[name]
        assert 'actual-report-artifact' in prompts[name]
        assert hashlib.sha256(report.read_bytes()).hexdigest() in prompts[name]
    assert record['prior_decisions'][0]['prior_review_documents'][0]['stage'] == 'pre_final'
    assert record['merged']['outcome'] == 'ready'


def test_historical_reports_require_matching_digest(tmp_path, monkeypatch):
    metadata, report = _historical_report_metadata(tmp_path, monkeypatch)
    report.write_text('A different actual report.\n')
    with pytest.raises(ValueError, match='report source changed'):
        flow.prior_decisions('p', metadata, tmp_path)


@pytest.mark.parametrize('unsafe', ['absolute', 'traversal', 'file_symlink', 'directory_symlink',
                                  'missing', 'oversized', 'bad_digest', 'invalid_utf8', 'empty'])
def test_historical_report_sources_fail_closed(tmp_path, monkeypatch, unsafe):
    metadata, report = _historical_report_metadata(tmp_path, monkeypatch)
    document = metadata['journal_prior_review_documents'][0]
    if unsafe == 'absolute':
        document['path'] = str(report)
    elif unsafe == 'traversal':
        document['path'] = 'reports/../reports/expert-1.txt'
    elif unsafe == 'file_symlink':
        (report.parent / 'linked.txt').symlink_to(report)
        document['path'] = 'reports/linked.txt'
    elif unsafe == 'directory_symlink':
        (tmp_path / 'linked').symlink_to(report.parent, target_is_directory=True)
        document['path'] = 'linked/expert-1.txt'
    elif unsafe == 'missing':
        report.unlink()
    elif unsafe == 'oversized':
        report.write_bytes(b'x' * 2_000_001)
        document['sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    elif unsafe == 'bad_digest':
        document['sha256'] = 'invalid'
    elif unsafe == 'invalid_utf8':
        report.write_bytes(b'\xff')
        document['sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    else:
        report.write_text(' \n')
        document['sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='Historical expert report'):
        flow.prior_decisions('p', metadata, tmp_path)


@pytest.mark.parametrize('change', ['final_stage', 'summary_kind', 'unauthenticated', 'missing_provenance',
                                  'unmatched_journal', 'unmatched_number', 'duplicate',
                                  'inline_text', 'wrong_size'])
def test_historical_reports_require_authentic_pre_final_attempt_binding(tmp_path, monkeypatch, change):
    metadata, _ = _historical_report_metadata(tmp_path, monkeypatch)
    document = metadata['journal_prior_review_documents'][0]
    if change == 'final_stage':
        document['stage'] = 'final_refusal'
    elif change == 'summary_kind':
        document['source_kind'] = 'internal_summary'
    elif change == 'unauthenticated':
        document['provenance']['authenticated'] = False
    elif change == 'missing_provenance':
        document.pop('provenance')
    elif change == 'unmatched_journal':
        document['journal'] = 'Other'
    elif change == 'unmatched_number':
        document['manuscript_number'] = 'Other'
    elif change == 'inline_text':
        document['text'] = 'Author-supplied paraphrase, not file contents'
    elif change == 'wrong_size':
        document['bytes'] = 1
    else:
        metadata['journal_prior_review_documents'].append(dict(document))
    with pytest.raises(ValueError):
        flow.prior_decisions('p', metadata, tmp_path)


@pytest.mark.parametrize('change', ['bytes', 'hash_and_bytes', 'provenance', 'remove', 'add', 'symlink'])
def test_post_review_historical_report_mutation_invalidates_context(tmp_path, monkeypatch, change):
    metadata, report = _historical_report_metadata(tmp_path, monkeypatch)
    record = {'prior_decisions': flow.prior_decisions('p', metadata, tmp_path)}
    assert flow.rejection_context_blockers(record, metadata, tmp_path) == []
    document = metadata['journal_prior_review_documents'][0]
    if change in {'bytes', 'hash_and_bytes'}:
        report.write_text('New report text.\n')
        if change == 'hash_and_bytes':
            document['sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    elif change == 'provenance':
        document['provenance']['artifact_id'] = 'different-authenticated-artifact'
    elif change == 'remove':
        metadata.pop('journal_prior_review_documents')
    elif change == 'add':
        extra = report.parent / 'expert-2.txt'
        extra.write_text('Newly recovered second report.\n')
        metadata['journal_prior_review_documents'].append(document | {
            'path': 'reports/expert-2.txt', 'sha256': hashlib.sha256(extra.read_bytes()).hexdigest()})
    else:
        real = report.parent / 'real.txt'
        report.rename(real)
        report.symlink_to(real)
    assert flow.rejection_context_blockers(record, metadata, tmp_path)


def test_absent_historical_reports_preserve_legacy_context_and_new_reports_invalidate_it(tmp_path, monkeypatch):
    metadata, _ = _historical_report_metadata(tmp_path, monkeypatch)
    legacy_metadata = {'journal_rejections': metadata['journal_rejections']}
    decisions = flow.prior_decisions('p', legacy_metadata, tmp_path)
    assert 'prior_review_documents' not in decisions[0]
    record = {'prior_decisions': decisions}
    assert flow.rejection_context_blockers(record, legacy_metadata, tmp_path) == []
    assert flow.rejection_context_blockers(record, metadata, tmp_path)


def test_inline_bibliography_takes_priority_over_unused_stale_bbl(tmp_path):
    (tmp_path / 'main.tex').write_text('\\begin{thebibliography}{9}\n\\bibitem{math}Actual mathematical predecessor.\\end{thebibliography}')
    (tmp_path / 'main.bbl').write_text('Stale support-only bibliography')
    text = flow.bibliography_text(tmp_path)
    assert 'Actual mathematical predecessor' in text and 'Stale' not in text


def test_empirical_editor_receives_results_numbers_and_budgets(tmp_path):
    (tmp_path / 'numbers.tex').write_text(r'\newcommand{\Cov}{0.9026}')
    (tmp_path / 'results.tex').write_text(
        r'\section{Results} Coverage \Cov.\subsection{Costs} 300 target labels.')
    (tmp_path / 'main.tex').write_text(
        r'\input{numbers}\title{Benchmark}\begin{abstract}Coverage \Cov.\end{abstract}'
        '\n' + r'\section{Introduction} Question.\section{Methods} Labels revealed only in target calibration.'
        '\n' + r'\input{results}\section{Discussion} Limits.')
    parts = flow.front_matter(flow.expand_tex(tmp_path / 'main.tex', tmp_path))
    assert parts['title'] == 'Benchmark'
    assert parts['abstract'] == 'Coverage 0.9026.'
    assert 'Coverage 0.9026.' in parts['main_statements']
    assert '300 target labels' in parts['main_statements']
    assert 'Limits.' not in parts['main_statements']
    assert 'Labels revealed only in target calibration' in parts['methods']


def test_expand_handles_multiple_inputs_without_expanding_comments(tmp_path):
    (tmp_path / 'a.tex').write_text('FIRST')
    (tmp_path / 'b.tex').write_text('SECOND')
    (tmp_path / 'c.tex').write_text('COMMENTED')
    (tmp_path / 'main.tex').write_text(r'prefix\input{a}between\input{b}suffix % \input{c}')
    expanded = flow.expand_tex(tmp_path / 'main.tex', tmp_path)
    assert all(s in expanded for s in ('prefix', 'FIRST', 'between', 'SECOND', 'suffix'))
    assert 'COMMENTED' not in expanded


def test_referee_receives_supplement_and_inspectable_scientific_paths(tmp_path, monkeypatch):
    manuscript = tmp_path / 'paper'
    manuscript.mkdir()
    (manuscript / 'supplementary.tex').write_text(r'\section{Sensitivity}\input{table}')
    (manuscript / 'table.tex').write_text('Independent control objective gap: 0.000001.')
    code = tmp_path / 'public-support' / 'solver.py'
    code.parent.mkdir()
    code.write_text('scientific implementation')
    meta = {'paper_id': 'p', 'manuscript_dir': 'paper',
            'support': {'publication': {'source_files': ['public-support/solver.py']}}}
    monkeypatch.setattr(flow, '_target_block', lambda metadata, track='routine': 'Journal')
    packet = flow.referee_packet({'metadata': meta, 'expanded': 'Main paper', 'bibliography': 'Refs'},
                                 tmp_path, None)
    assert 'Independent control objective gap: 0.000001.' in packet
    assert str(code.resolve()) in packet
    assert 'private preparation notes are not review inputs' in packet


def test_unused_source_files_are_reported(tmp_path):
    for name in ("main.tex", "used.tex", "old.tex", "notes.md", "references.bib"):
        (tmp_path / name).write_text("x")
    assert flow.unused_source_files(tmp_path, {"used.tex", "references.bib"}) == ["old.tex"]
    assert flow.unused_source_files(tmp_path, {"used.tex"}) == ["old.tex"]


def test_unified_release_validation(tmp_path, monkeypatch):
    mock_formal_stage(monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    record = {"merged": {"outcome": "ready"}, "editor_screen": {"decision": "send_to_review"},
              "fingerprints": {"manuscript_snapshot_sha256": "a" * 64}, "target_journal": "J",
              'review_policy_sha256': flow.review_policy_sha256(config),
              'referee_reports': {'referee_b': referee()}, 'prior_decisions': []}
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(record))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {"target_journal": "J", "writing_release": {"review_process": "unified_v1",
            "decision_record": "decision.json", "decision_record_sha256": digest}}
    assert flow.validate_unified_release("p", meta, tmp_path, "a" * 64) == []
    assert flow.validate_unified_release("p", meta, tmp_path, "b" * 64)
    assert flow.validate_unified_release("p", meta | {"target_journal": "K"}, tmp_path, "a" * 64)
    legacy = {"target_journal": "J", "writing_release": {"status": "ready"}}
    assert flow.validate_unified_release("p", legacy, tmp_path, "a" * 64)


def test_original_rejection_letter_is_loaded_and_hash_bound(tmp_path, monkeypatch):
    monkeypatch.delenv('ARA_PAPER_MANAGE_API_URL', raising=False)
    path = tmp_path / 'letter.json'
    path.write_text(json.dumps({'body': 'Results are borderline for our readers.'}))
    meta = {'journal_rejections': [{'journal': 'J', 'manuscript_number': '123',
                                   'source': 'letter.json', 'rejected_at': '2026-10-01'}]}
    rows = flow.prior_decisions('p', meta, tmp_path)
    assert rows[0]['letter_text'] == 'Results are borderline for our readers.'
    assert rows[0]['source_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    report = {'decision_id': rows[0]['decision_id'], 'journal': 'J', 'judgment': 'compatible',
              'answered': False, 'evidence': 'The result is still borderline for J; target K publishes this class, Section 1.'}
    ed = editor() | {'prior_rejections_addressed': [report]}
    assert flow.rejection_clearance_blockers(ed, rows) == []
    report['judgment'] = 'unresolved'
    assert flow.merge(ed, {}, flow.rejection_clearance_blockers(ed, rows))['outcome'] == 'rejection_history_blocked'
    assert flow.rejection_clearance_blockers(editor(), rows)
    path.unlink()
    assert flow.rejection_clearance_blockers(ed, flow.prior_decisions('p', meta, tmp_path))


def test_single_referee_requires_authorization_and_retains_blockers(monkeypatch):
    settings = {'review': {'referee_roles': ['referee_b']}}
    monkeypatch.setattr(flow, 'load_registry_settings', lambda root: settings)
    with pytest.raises(ValueError, match='authorization'):
        flow.review_config('x')
    settings['review']['single_referee_authorization'] = {'actor': 'user', 'quote': 'one referee temporarily'}
    assert flow.review_config('x')['referee_roles'] == ['referee_b']
    assert flow.merge(editor(), {'referee_b': referee('accept')})['outcome'] == 'ready'
    assert flow.merge(editor(), {'referee_b': referee('accept', blockers=['proof gap'])})['outcome'] != 'ready'
    with pytest.raises(ValueError, match='panel'):
        flow.merge(editor(), {})


def test_optional_previous_suggestions_cannot_become_unresolved_mandatory_items():
    schema = flow.referee_schema_for_previous({'items': [], 'letter': 'Optional: shorten a transition.'})
    sub = schema['properties']['previous_items']
    _validate_against_schema([], sub)
    with pytest.raises(LaunchError, match='count'):
        _validate_against_schema([{'item': 'Optional transition', 'resolved': False, 'evidence': 'unchanged'}], sub)
    sub = flow.referee_schema_for_previous({'items': ['Fix Lemma 2 proof gap']})['properties']['previous_items']
    with pytest.raises(LaunchError):
        _validate_against_schema([], sub)
    _validate_against_schema([{'item': 'Fix Lemma 2 proof gap', 'resolved': False, 'evidence': 'still absent'}], sub)


def test_new_refusal_or_changed_letter_invalidates_clearance(tmp_path):
    row = {'journal': 'J', 'manuscript_number': '1'}
    identity = hashlib.sha256(json.dumps(['J', '1'], ensure_ascii=False).encode()).hexdigest()[:20]
    path = tmp_path / 'original.json'; path.write_text('original letter')
    bound = {'decision_id': identity, 'letter_available': True, 'letter_source': 'original.json',
             'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    record = {'prior_decisions': [bound]}
    metadata = {'journal_rejections': [row]}
    assert flow.rejection_context_blockers(record, metadata, tmp_path) == []
    metadata['journal_rejections'].append({'journal': 'K', 'manuscript_number': '2'})
    assert flow.rejection_context_blockers(record, metadata, tmp_path)
    metadata['journal_rejections'].pop(); path.write_text('different letter')
    assert flow.rejection_context_blockers(record, metadata, tmp_path)


@pytest.mark.parametrize('clear', [True, False])
def test_run_starts_only_active_referee_after_rejection_clearance(tmp_path, monkeypatch, clear):
    mock_formal_stage(monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_a': {'provider': 'anthropic'}, 'referee_b': {'provider': 'openai-codex'}},
              'referee_roles': ['referee_b'], 'rejection_clearance_required': True,
              'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    pre = {'metadata': {'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
           'fingerprints': {}, 'expanded': 'x', 'bibliography': ''}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    decisions = [{'decision_id': 'd', 'journal': 'J', 'manuscript_number': '1',
                  'letter_available': True}]
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: decisions)
    calls = []
    def role(**kw):
        name = kw['role_name']; calls.append(name)
        if name == 'editor':
            return editor() | {'prior_rejections_addressed': [{'decision_id': 'd', 'journal': 'J',
                'answered': clear, 'judgment': 'resolved' if clear else 'unresolved', 'evidence': 'Section 2'}]}, {}
        if name == 'decision_letter':
            return {'letter': 'fixed decision'}, {}
        return referee('accept'), {}
    monkeypatch.setattr(flow, 'run_role', role)
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert ('referee_b' in calls) == clear
    assert 'referee_a' not in calls
    assert record['single_referee_panel'] is True
    assert record['merged']['outcome'] == ('ready' if clear else 'rejection_history_blocked')


def test_artifact_uri_recorded_on_another_workstation_resolves_locally(tmp_path):
    from paper_writing.support import SupportPackageError, _artifact_uri_path

    root = tmp_path / "openlabs-data"
    root.mkdir()
    (tmp_path / "openlabs-artifacts").mkdir()
    digest = "a" * 64
    uri = f"file:///home/other/work/openlabs-artifacts/paper-support/sha256/{digest}/pkg.zip"
    assert _artifact_uri_path(root, uri, digest) == tmp_path / "openlabs-artifacts/paper-support/sha256" / digest / "pkg.zip"
    with pytest.raises(SupportPackageError):
        _artifact_uri_path(root, f"file:///home/other/openlabs-artifacts/elsewhere/{digest}/pkg.zip", digest)
    with pytest.raises(SupportPackageError):
        _artifact_uri_path(root, f"file:///home/other/openlabs-artifacts/paper-support/sha256/{'b' * 64}/pkg.zip", digest)


def test_unified_release_snapshot_marks_score_informational():
    from paper_writing.handoff import _release_snapshot

    snapshot = _release_snapshot({"writing_release": {"status": "ready", "review_process": "unified_v1", "score": 7}})
    assert "target_score" not in snapshot and snapshot["score"] == 7 and snapshot["score_role"] == "informational"
    assert snapshot["review_process"] == "unified_v1"
    legacy_record = {"writing_release": {"status": "ready", "review_process": "unified_v1"},
                     "ara_llm_self_review": {"source": "reviews/old/review.json"}}
    assert "review_record" not in _release_snapshot(legacy_record)
    assert snapshot["quality_gate_schema"] == "openlabs.review.decision.v1"
    legacy = _release_snapshot({"writing_release": {"status": "ready", "score": 6, "target_score": 6.0}})
    assert legacy["target_score"] == 6.0 and "score_role" not in legacy


def test_standalone_documents_count_as_used(tmp_path):
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "t1.tex").write_text("x")
    (tmp_path / "supplementary.tex").write_text("\\documentclass{article}\n\\input{tables/t1}\n")
    (tmp_path / "draft.tex").write_text("\\section{Old}")
    used = flow.standalone_document_files(tmp_path)
    assert used == {"supplementary.tex", "tables/t1.tex"}
    assert flow.unused_source_files(tmp_path, used) == ["draft.tex"]


def test_build_reads_registered_document_recorder_and_declared_bibstyle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    manuscript = tmp_path / 'manuscript'
    manuscript.mkdir()
    for name, text in {'main.tex': 'Main', 'si.tex': 'Supplement',
                       'si-class.cls': 'Class', 'si-style.bst': 'Style',
                       'unused.sty': 'Unused'}.items():
        (manuscript / name).write_text(text)

    def compile_document(command, *, cwd, **kwargs):
        assert command[-1] == 'si.tex'
        (cwd / 'si.pdf').write_bytes(b'fresh supplement PDF')
        (cwd / 'si.fls').write_text('INPUT ./si.tex\nINPUT ./si-class.cls\n')
        (cwd / 'si.aux').write_text('\\bibstyle{si-style}\n')
        return SimpleNamespace(returncode=0, stdout='built', stderr='')

    monkeypatch.setattr(flow.subprocess, 'run', compile_document)
    pdf, used = flow._build(manuscript, tmp_path / 'work', document='si.tex')
    assert pdf.name == 'si.pdf'
    assert used == {'si.tex', 'si-class.cls', 'si-style.bst'}
    assert flow.unused_source_files(manuscript, used) == ['unused.sty']


def test_registered_supplement_refreshes_pdf_bbl_and_dependencies(tmp_path, monkeypatch):
    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'si.tex').write_text('SI')
    (manuscript / 'si.pdf').write_bytes(b'old PDF')
    built = tmp_path / 'fresh/si.pdf'
    built.parent.mkdir()
    built.write_bytes(b'fresh PDF')
    built.with_suffix('.bbl').write_text('fresh bibliography')

    def build(source, workdir, *, document):
        assert source == manuscript and document == 'si.tex'
        assert workdir == tmp_path / 'work/supplement'
        return built, {'si.tex', 'si-class.cls', 'si-style.bst'}

    monkeypatch.setattr(flow, '_build', build)
    metadata = {'latest_supplementary_pdf': 'papers/p/manuscript/si.pdf'}
    used = flow.build_registered_supplement(metadata, tmp_path, manuscript, tmp_path / 'work')
    assert used == {'si.tex', 'si-class.cls', 'si-style.bst'}
    assert (manuscript / 'si.pdf').read_bytes() == b'fresh PDF'
    assert (manuscript / 'si.bbl').read_text() == 'fresh bibliography'
    assert flow.build_registered_supplement({}, tmp_path, manuscript, tmp_path / 'work') == set()


def test_registered_supplement_rejects_source_outside_manuscript(tmp_path):
    (tmp_path / 'outside.tex').write_text('Not a manuscript source')
    with pytest.raises(ValueError, match='manuscript-root'):
        flow.build_registered_supplement({'latest_supplementary_pdf': 'outside.pdf'},
                                         tmp_path, tmp_path / 'manuscript', tmp_path / 'work')


def test_support_inventory_keeps_directories(tmp_path):
    pkg = tmp_path / "papers/p/support/v1"
    (pkg / "verification").mkdir(parents=True)
    (pkg / "README.md").write_text("readme")
    (pkg / "verification" / "check.py").write_text("x")
    meta = {"support": {"publication": {"source_files": ["papers/p/support/v1/README.md",
                                                          "papers/p/support/v1/verification/check.py"]}}}
    text = flow.support_description(meta, tmp_path)
    assert "- verification/check.py" in text and "- README.md" in text


def test_referee_receives_original_refusal_without_current_editor_verdict(tmp_path):
    pre = {'metadata': {'paper_id':'p', 'target_journal':'Journal'},
           'expanded':'Current manuscript', 'bibliography':'Current bibliography'}
    decisions = [{'decision_id':'D-1', 'letter_available':True, 'letter_text':'Original concern'}]
    packet = flow.referee_packet(pre, tmp_path, None, decisions)
    assert 'Original concern' in packet and 'D-1' in packet
    assert 'Current manuscript' in packet and 'send_to_review' not in packet


def _current_claim_map_package(tmp_path):
    from paper_writing.support import SUPPORT_ARCHIVE_SCHEMA_VERSION

    source = 'papers/p/support-materials/code-first-v2/CLAIM-EVIDENCE.md'
    path = tmp_path / source
    path.parent.mkdir(parents=True)
    text = 'Current selected evidence: exact complete producer chain.\n'
    path.write_text(text)
    member = 'p-support-v2/support-materials/code-first-v2/CLAIM-EVIDENCE.md'
    manifest = {'schema_version': SUPPORT_ARCHIVE_SCHEMA_VERSION, 'paper_id': 'p', 'paper_version': '2',
                'files': [{'archive_path': member, 'size': len(path.read_bytes()),
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]}
    payload = {member: path.read_bytes(),
               'p-support-v2/ZENODO_MANIFEST.json': json.dumps(manifest).encode()}
    sums = '\n'.join(f'{hashlib.sha256(value).hexdigest()}  {name}' for name, value in payload.items()) + '\n'
    archive = tmp_path / 'current-support.zip'
    with zipfile.ZipFile(archive, 'w') as package:
        for name, content in payload.items():
            package.writestr(name, content)
        package.writestr('p-support-v2/SHA256SUMS', sums)
    metadata = {'paper_id': 'p', 'support': {'publication': {'source_files': [source],
                'package_files': ['current-support.zip'],
                'package_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}}}
    canonical = tmp_path / 'papers/p/evidence/claim_evidence_map.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('Stale canonical evidence: missing the current producer.\n')
    return metadata, path, archive, canonical


def test_role_packets_embed_current_selected_map_not_stale_canonical(tmp_path):
    metadata, path, archive, canonical = _current_claim_map_package(tmp_path)
    maps = flow.selected_claim_evidence_maps(metadata, tmp_path)
    pre = {'metadata': metadata, 'expanded': 'Current manuscript', 'bibliography': 'Refs',
           'support_claim_evidence_maps': maps}
    newer = tmp_path / 'papers/p/support-materials/code-first-v999/CLAIM-EVIDENCE.md'
    newer.parent.mkdir(parents=True)
    newer.write_text('Unregistered evidence must never be selected.\n')
    for packet in (flow.editor_packet(pre, []), flow.referee_packet(pre, tmp_path, None)):
        assert path.read_text() in packet
        assert canonical.read_text() not in packet and newer.read_text() not in packet
        assert maps[0]['source'] in packet and maps[0]['archive_member'] in packet
        assert hashlib.sha256(path.read_bytes()).hexdigest() in packet
        assert hashlib.sha256(archive.read_bytes()).hexdigest() in packet
    # Direct callers also use the same registered selection instead of canonical.
    del pre['support_claim_evidence_maps']
    assert path.read_text() in flow.referee_packet(pre, tmp_path, None)


def test_no_selected_claim_map_preserves_canonical_packet_bytes(tmp_path):
    canonical = tmp_path / 'papers/p/evidence/claim_evidence_map.md'
    canonical.parent.mkdir(parents=True)
    canonical.write_text('Canonical legacy evidence.\n')
    pre = {'metadata': {'paper_id': 'p'}, 'expanded': 'Main', 'bibliography': 'Refs'}
    legacy = flow.referee_packet(pre, tmp_path, None)
    assert '## Claim-evidence map\nCanonical legacy evidence.\n' in legacy
    pre['support_claim_evidence_maps'] = []
    assert flow.referee_packet(pre, tmp_path, None) == legacy
    editor = flow.editor_packet(pre, [])
    del pre['support_claim_evidence_maps']
    assert flow.editor_packet(pre, []) == editor


@pytest.mark.parametrize('problem', ['missing', 'changed', 'archive_hash', 'corrupt_archive',
                                    'traversal', 'symlink', 'duplicate'])
def test_declared_selected_map_fails_closed_instead_of_falling_back(tmp_path, problem):
    metadata, path, archive, canonical = _current_claim_map_package(tmp_path)
    publication = metadata['support']['publication']
    if problem == 'missing':
        path.unlink()
    elif problem == 'changed':
        path.write_text('Current source changed after archive preparation.\n')
    elif problem == 'archive_hash':
        publication['package_sha256'] = '0' * 64
    elif problem == 'corrupt_archive':
        archive.write_bytes(b'not a support ZIP')
        publication['package_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif problem == 'traversal':
        publication['source_files'] = ['../outside/CLAIM-EVIDENCE.md']
    elif problem == 'symlink':
        path.unlink()
        path.symlink_to(canonical)
    elif problem == 'duplicate':
        publication['source_files'] *= 2
    pre = {'metadata': metadata, 'expanded': 'Main', 'bibliography': 'Refs'}
    with pytest.raises(ValueError):
        flow.referee_packet(pre, tmp_path, None)


def test_preflight_records_selected_map_failure_before_roles(tmp_path, monkeypatch):
    from paper_writing import manuscript_style, operations, support_citations, journal_history

    metadata, path, archive, canonical = _current_claim_map_package(tmp_path)
    metadata.update(target_journal='J', target_journal_fit={'status': 'approved'})
    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir()
    (manuscript / 'main.tex').write_text(
        r'\begin{thebibliography}{9}\bibitem{mainref}Main reference.\end{thebibliography}')
    (manuscript / 'supplementary.tex').write_text(
        r'\begin{thebibliography}{9}\bibitem{siref}Supplement-only reference.\end{thebibliography}')
    pdf = tmp_path / 'built.pdf'
    pdf.write_bytes(b'fixture PDF')
    path.write_text('Actual declared source no longer matches the verified archive.\n')
    monkeypatch.setattr(flow, 'load_registry', lambda *args, **kwargs: None)
    # This fixture isolates selected-map integrity, not journal-history policy.
    monkeypatch.setattr(journal_history, 'guard_target', lambda *args, **kwargs: None)
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args, **kwargs: metadata)
    monkeypatch.setattr(flow, '_build', lambda *args, **kwargs: (pdf, {'main.tex'}))
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style', lambda *args, **kwargs: {})
    monkeypatch.setattr(manuscript_style, 'manuscript_style_blockers', lambda *args: [])
    monkeypatch.setattr(support_citations, 'audit_manuscript_support', lambda *args, **kwargs: {})
    monkeypatch.setattr(support_citations, 'support_audit_blockers', lambda *args: [])
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: {})
    pre = flow.preflight('p', tmp_path, tmp_path / 'build')
    assert any('Selected support claim-evidence map' in b and 'bytes differ' in b for b in pre['blockers'])
    assert pre['support_claim_evidence_maps'] == []
    # Ordinary editor/referee packets must see the same complete printed
    # bibliography that the mandatory reference verifier receives.
    assert 'mainref' in pre['bibliography']
    assert 'siref' in pre['bibliography']


# --------------------------------------------------------------------------- convergence changes

def scored(significance, novelty, rec="minor_revision", changes=()):
    report = referee(rec, changes=changes)
    report["scores"] = {"overall": 6, "clarity": 6, "soundness": 6,
                        "significance": significance, "novelty": novelty}
    return report


def refereed_round(significance, novelty):
    return {"referee_reports": {"referee_a": scored(significance, novelty),
                                "referee_b": scored(significance, novelty)}}


def test_stalled_flag_when_significance_and_novelty_do_not_rise():
    rounds = [refereed_round(5, 5), refereed_round(5, 4)]
    referees = {"referee_a": scored(5, 4), "referee_b": scored(4, 4)}
    merged = flow.merge(editor(), referees)
    signal = flow.stalled_signal(rounds, referees, merged)
    assert signal["stalled"] is True
    # Only a flag: the readiness decision is unchanged.
    assert merged["outcome"] == "ready"


@pytest.mark.parametrize("case", ["rising_novelty", "evidence_requested", "too_few_rounds", "desk_round"])
def test_stalled_flag_is_not_set(case):
    rounds = [refereed_round(5, 5), refereed_round(5, 5)]
    referees = {"referee_a": scored(5, 5), "referee_b": scored(5, 5)}
    if case == "rising_novelty":
        referees = {"referee_a": scored(5, 6), "referee_b": scored(5, 6)}
    elif case == "evidence_requested":
        referees["referee_b"] = scored(5, 5, "major_revision", changes=[("add an ablation", "evidence")])
    elif case == "too_few_rounds":
        rounds = rounds[:1]
    elif case == "desk_round":
        referees = {}
    merged = flow.merge(editor(), referees) if referees else flow.merge(editor("desk_reject", "scope"), {})
    assert flow.stalled_signal(rounds, referees, merged)["stalled"] is False


def test_rounds_without_referees_do_not_count_toward_stall_window():
    rounds = [refereed_round(5, 5), {"editor_screen": {"decision": "desk_reject"}}, refereed_round(5, 5)]
    referees = {"referee_a": scored(5, 5), "referee_b": scored(5, 5)}
    assert flow.stalled_signal(rounds, referees, flow.merge(editor(), referees))["stalled"] is True


def test_review_policy_hash_ignores_code_and_prompt_files(tmp_path, monkeypatch):
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    before = flow.review_policy_sha256(config)
    edited = tmp_path / "formal.md"
    edited.write_text("edited prompt")
    monkeypatch.setattr(flow.formal_checks, "PROMPT", edited)
    assert flow.review_policy_sha256(config) == before
    monkeypatch.setattr(flow.formal_checks, "POLICY_VERSION", flow.formal_checks.POLICY_VERSION + 1)
    assert flow.review_policy_sha256(config) != before


def test_legacy_review_policy_record_still_matches(tmp_path, monkeypatch):
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True}
    legacy = {"schema": flow.formal_checks.VERSION, "mandatory": True, "implementation_sha256": "1" * 64,
              "launcher_sha256": "2" * 64, "prompt_sha256": "3" * 64, "schema_sha256": "4" * 64}
    (tmp_path / "report.json").write_text(json.dumps({"policy": legacy}))
    record = {"review_policy_sha256": flow.review_policy_sha256(config, formal_policy=legacy),
              "formal_check": {"path": "report.json"}}
    assert flow.review_policy_matches(record, config, tmp_path)
    changed = dict(config, referee_roles=['referee_a'])
    assert not flow.review_policy_matches(record, changed, tmp_path)
    monkeypatch.setattr(flow.formal_checks, "POLICY_VERSION", flow.formal_checks.POLICY_VERSION + 1)
    assert not flow.review_policy_matches(record, config, tmp_path)


MANUSCRIPT = r"""\documentclass{article}
\newcommand{\effect}{0.42}
\begin{document}
\title{County water prices}
\begin{abstract}Prices fell by \effect{} after reform.\end{abstract}
\section{Introduction}
We study water prices.
\section{Data and methods}
We use 120 counties. The estimator follows a standard design.
\begin{figure}\includegraphics[width=0.8\textwidth]{fig1.png}\caption{Prices over time.}\end{figure}
\section{Results}
The effect is \effect{}.
\begin{table}\begin{tabular}{cc}a & 1.5\\\end{tabular}\end{table}
\section{Conclusion}
Prices fell.
\end{document}
"""


@pytest.mark.parametrize("edit,unchanged", [
    (("The estimator follows a standard design.", "The estimator follows the standard two-way design."), True),
    (("width=0.8", "width=0.6"), True),
    (("Prices over time.}", "Prices over time.}% checked 2026-11-11, 3 panels"), True),
    (("\\newcommand{\\effect}{0.42}", "\\newcommand{\\effect}{0.40}"), False),
    (("We use 120 counties.", "We use 118 counties."), False),
    (("We use 120 counties.", "We use 120 in total."), True),
    (("We use 120 counties.", "We use 118 in total."), False),
    (("a & 1.5", "a & 1.6"), False),
    (("Prices fell.\n\\end", "Prices fell sharply.\n\\end"), False),
    (("We study water prices.", "We study water prices in arid regions."), False),
    (("County water prices", "Urban water prices"), False),
])
def test_substantive_delta_rule(edit, unchanged):
    old, new = edit
    assert old in MANUSCRIPT
    result = flow.substantive_delta(MANUSCRIPT, MANUSCRIPT.replace(old, new))
    assert result["substantive_unchanged"] is unchanged, result["reasons"]
    if unchanged and old != new:
        assert result["summary"]["lines_added"] >= 1


def test_substantive_delta_rejects_large_rewrites():
    filler = "".join(f"Method sentence {chr(97 + i % 26)}.\n" for i in range(10))
    old = MANUSCRIPT.replace("We use 120 counties.", "We use 120 counties.\n" + filler)
    new = old.replace(filler, filler.replace("Method sentence", "Method clause"))
    result = flow.substantive_delta(old, new)
    assert not result["substantive_unchanged"] and "lines changed" in result["reasons"][-1]


def _delta_fixture(tmp_path, monkeypatch, expanded):
    mock_formal_stage(monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_a': {'provider': 'anthropic', 'model': 'opus'},
              'referee_b': {'provider': 'openai-codex', 'model': 'gpt'}},
              'referee_roles': ['referee_a', 'referee_b'], 'rejection_clearance_required': True,
              'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    base = tmp_path / "reviews/unified/p/20200101T000000Z"
    base.mkdir(parents=True)
    (base / "manuscript-expanded.tex").write_text(MANUSCRIPT)
    record = {"stage_reached": "decision", "target_journal": "J", "run_id": "20200101T000000Z",
              "review_policy_sha256": flow.review_policy_sha256(config), "review_track": {"track": "routine"},
              "editor_screen": editor() | {"prior_rejections_addressed": []},
              "referee_reports": {"referee_a": referee("accept"), "referee_b": referee("minor_revision")},
              "merged": {"outcome": "ready", "scientific_blockers": [], "required_changes": []},
              "prior_decisions": [], "letter": "Accepted with minor wording suggestions.",
              "receipts": {"editor": {"model": "gpt"}}}
    (base / "decision.json").write_text(json.dumps(record))
    pre = {'metadata': {'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
           'fingerprints': {}, 'expanded': expanded, 'bibliography': ''}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: [])
    calls = []

    def role(**kw):
        calls.append(kw['role_name'])
        if kw['role_name'] == 'editor':
            return editor() | {'prior_rejections_addressed': []}, {}
        if kw['role_name'] == 'decision_letter':
            return {'letter': 'fresh letter'}, {}
        return referee('accept'), {}
    monkeypatch.setattr(flow, 'run_role', role)
    return calls


def test_text_only_change_after_ready_reuses_the_review(tmp_path, monkeypatch):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace(
        "The estimator follows a standard design.", "The estimator follows the standard two-way design."))
    formal_runs = []
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda *args: formal_runs.append(1) or {'valid': True, 'blockers': []})
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert calls == []  # no editor, referee or letter model was started
    assert formal_runs == [1]  # the mandatory reference/core verification still reran
    assert record["review_mode"] == "delta" and record["merged"]["outcome"] == "ready"
    assert record["consumes_scientific_round"] is False
    assert record["delta_review"]["basis_run_id"] == "20200101T000000Z"
    assert record["delta_review"]["summary"]["sections_touched"] == ["Data and methods"]
    assert record["letter"] == "Accepted with minor wording suggestions."


def test_numeric_change_after_ready_requires_full_review(tmp_path, monkeypatch):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace("120 counties", "118 counties"))
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert 'editor' in calls and 'referee_a' in calls and 'referee_b' in calls
    assert record.get("review_mode") != "delta"
    assert any("numbers changed" in r for r in record["delta_review_refused"]["reasons"])
    assert record["merged"]["outcome"] == "ready" and record["merged"]["stalled"] is False


def test_policy_change_after_ready_requires_full_review(tmp_path, monkeypatch):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace("width=0.8", "width=0.6"))
    monkeypatch.setattr(flow.formal_checks, "POLICY_VERSION", flow.formal_checks.POLICY_VERSION + 1)
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert 'referee_a' in calls
    assert "review policy changed since the ready review" in record["delta_review_refused"]["reasons"]


def _apply_fixture(tmp_path, monkeypatch):
    from paper_writing import operations
    mock_formal_stage(monkeypatch)
    meta = {'paper_id': 'p', 'version': '1.0', 'target_journal': 'J'}
    written = []
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args: meta)
    monkeypatch.setattr(flow, 'write_paper_metadata', lambda pid, value, root: written.append(copy.deepcopy(value)))
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: {})
    return meta, written


def test_direction_decision_is_applied_as_a_machine_readable_block(tmp_path, monkeypatch):
    meta, written = _apply_fixture(tmp_path, monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True, 'max_rounds_per_target': 10, 'previous_panels': []}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    screen = editor("desk_reject", "incremental") | {"strongest_desk_reject_reason": "Same as Lee 2023.",
                                                     "closest_prior_work": []}
    record = {"paper_id": "p", "target_journal": "J", "manuscript_version": "1.0", "finished_at": "2026-11-11T00:00:00Z",
              "round_for_target": 1, "review_policy_sha256": flow.review_policy_sha256(config),
              "prior_decisions": [], "editor_screen": screen, "referee_reports": {},
              "merged": flow.merge(screen, {}), "fingerprints": {}}
    path = tmp_path / "decision.json"; path.write_text(json.dumps(record))
    release = flow.apply_decision('p', root=tmp_path, decision_path=path, digest=flow._sha256(path.read_bytes()))
    assert release["status"] == "blocked" and release["next_action"] == "direction_decision"
    assert release["direction_context"]["strongest_desk_reject_reason"] == "Same as Lee 2023."


def test_delta_review_record_passes_apply_revalidation(tmp_path, monkeypatch):
    calls = _delta_fixture(tmp_path, monkeypatch, MANUSCRIPT.replace("width=0.8", "width=0.6"))
    meta, written = _apply_fixture(tmp_path, monkeypatch)
    record = flow.run_review('p', root=tmp_path, apply=True)
    assert calls == [] and record["review_mode"] == "delta"
    release = written[-1]["writing_release"]
    assert release["status"] == "ready" and release["review_mode"] == "delta"
    assert release["delta_basis_run_id"] == "20200101T000000Z"


# --------------------------------------------------------------------------- formal checks: entry vs exit (2026-11)

def _formal_problem_preflight(tmp_path, monkeypatch, style_errors, support_errors, ledger=None):
    from paper_writing import manuscript_style, operations, support_citations

    metadata = {'paper_id': 'p', 'version': '1.0', 'target_journal': 'J',
                'target_journal_fit': {'status': 'approved'}}
    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'main.tex').write_text(
        '\\begin{document}\n\nFor real $x$, $x^2\\ge0$ by \\cite{mainref}.\n\n'
        r'\begin{thebibliography}{9}\bibitem{mainref}Main reference.\end{thebibliography}\end{document}')
    (manuscript / 'leftover.tex').write_text('not read by the build')
    pdf = tmp_path / 'built.pdf'
    pdf.write_bytes(b'%PDF-1.4 fixture')
    monkeypatch.setattr(flow, 'load_registry', lambda *args, **kwargs: None)
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args, **kwargs: metadata)
    monkeypatch.setattr(flow, '_build', lambda *args, **kwargs: (pdf, {'main.tex'}))
    style = {'errors': style_errors, 'blacklist_findings': [
        {'code': 'STYLE-INTERNAL-AUDIT', 'message': 'internal vocabulary', 'path': 'main.tex', 'line': 3,
         'context': 'We audit every smart-contract transfer on chain.'}], 'notes': []}
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style', lambda *args, **kwargs: style)
    monkeypatch.setattr(support_citations, 'audit_manuscript_support',
                        lambda *args, **kwargs: {'errors': support_errors})
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: {})
    from paper_writing import journal_history
    if ledger is None:
        monkeypatch.setattr(journal_history, 'guard_target', lambda *args, **kwargs: None)
    return flow.preflight('p', tmp_path, tmp_path / 'build')


FORMAL_STYLE_PROBLEMS = [
    {'code': 'STYLE-AI-DECLARATION-MISSING', 'message': 'add one AI-use declaration', 'path': 'main.tex'},
    {'code': 'STYLE-AI-DISCLOSURE-TOOL', 'message': 'name the recorded tool Codex', 'path': 'main.tex'},
    {'code': 'STYLE-UNRESOLVED-MARKER', 'message': 'remove TODO', 'path': 'main.tex', 'line': 9},
]
FORMAL_SUPPORT_PROBLEMS = [
    {'code': 'SUPPORT-DOI-MISSING', 'message': 'no current Zenodo Version DOI'},
    {'code': 'SUPPORT-STATUS-BEFORE-REVIEW', 'message': 'no draft before review'},
    {'code': 'SUPPORT-BIB-VERSION', 'message': 'version differs', 'path': 'references.bib'},
]


def test_formal_problems_become_preparation_advisories_not_preflight_blockers(tmp_path, monkeypatch):
    pre = _formal_problem_preflight(tmp_path, monkeypatch, FORMAL_STYLE_PROBLEMS, FORMAL_SUPPORT_PROBLEMS)
    assert pre['blockers'] == []
    codes = {a['code'] for a in pre['preparation_advisories']}
    assert {'STYLE-AI-DECLARATION-MISSING', 'STYLE-AI-DISCLOSURE-TOOL', 'STYLE-UNRESOLVED-MARKER',
            'STYLE-INTERNAL-AUDIT', 'SUPPORT-DOI-MISSING', 'SUPPORT-STATUS-BEFORE-REVIEW',
            'SUPPORT-BIB-VERSION', 'UNUSED-SOURCE-FILES'} <= codes
    audit = next(a for a in pre['preparation_advisories'] if a['code'] == 'STYLE-INTERNAL-AUDIT')
    assert audit['kind'] == 'internal_vocabulary' and 'smart-contract' in audit['context']
    assert pre['build_inputs'] == ['main.tex']


def test_evidence_hash_and_unreviewable_problems_still_block(tmp_path, monkeypatch):
    pre = _formal_problem_preflight(
        tmp_path, monkeypatch,
        [{'code': 'STYLE-MANUSCRIPT-MISSING', 'message': 'canonical manuscript source is missing'}],
        [{'code': 'SUPPORT-PACKAGE-HASH', 'message': 'support archive SHA-256 does not match the registry'},
         {'code': 'SUPPORT-SOMETHING-NEW', 'message': 'an unclassified future check'}])
    assert any(b.startswith('STYLE-MANUSCRIPT-MISSING') for b in pre['blockers'])
    assert any(b.startswith('SUPPORT-PACKAGE-HASH') for b in pre['blockers'])
    # Unknown codes are conservatively blocking.
    assert any(b.startswith('SUPPORT-SOMETHING-NEW') for b in pre['blockers'])


def test_run_review_records_advisories_without_preflight_failure(tmp_path, monkeypatch):
    mock_formal_stage(monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {'editor': {'provider': 'openai-codex'},
              'referee_a': {'provider': 'anthropic'}, 'referee_b': {'provider': 'openai-codex', 'model': 'g'}},
              'referee_roles': ['referee_b'], 'rejection_clearance_required': True,
              'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    advisories = [{'source': 'manuscript_style', 'kind': 'preparation', 'code': 'STYLE-AI-DECLARATION-MISSING',
                   'location': 'main.tex', 'message': 'add one AI-use declaration'}]
    pre = {'metadata': {'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
           'fingerprints': {}, 'expanded': 'x', 'bibliography': '', 'preparation_advisories': advisories,
           'build_inputs': ['main.tex']}
    monkeypatch.setattr(flow, 'preflight', lambda *args: pre)
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: [])
    monkeypatch.setattr(flow, 'run_role', lambda **kw: (
        (editor(), {}) if kw['role_name'] == 'editor' else
        ({'letter': 'fixed'}, {}) if kw['role_name'] == 'decision_letter' else (referee('accept'), {})))
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert record['merged']['outcome'] == 'ready'
    assert record['preparation_advisories'] == advisories and record['build_inputs'] == ['main.tex']


def test_delivery_exit_enforces_the_same_formal_problems(tmp_path, monkeypatch):
    from paper_writing import editorial_rewrite, manuscript_style, registry, support_citations

    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'main.tex').write_text('x')
    (manuscript / 'leftover.tex').write_text('not read by the build')
    monkeypatch.setattr(registry, 'load_registry_settings', lambda *args, **kwargs: {})
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style',
                        lambda *args, **kwargs: {'errors': FORMAL_STYLE_PROBLEMS, 'blacklist_findings': [
                            {'code': 'STYLE-INTERNAL-AUDIT', 'message': 'internal vocabulary'}]})
    monkeypatch.setattr(support_citations, 'audit_manuscript_support',
                        lambda *args, **kwargs: {'errors': FORMAL_SUPPORT_PROBLEMS})
    monkeypatch.setattr(editorial_rewrite, 'abstract_findings', lambda *args: ['abstract has 300 words'])
    notes = []
    access = {'references': {'u': ['https://api.crossref.org/works/u: ConnectTimeout']}, 'items': []}
    problems = flow.delivery_blockers('p', {'paper_id': 'p'}, tmp_path,
                                      {'build_inputs': ['main.tex'],
                                       'formal_check': {'unverifiable_source_access': access}}, notes=notes)
    assert {n['kind'] for n in notes} == {'internal_vocabulary', 'unverifiable_source_access'}
    joined = '\n'.join(problems)
    for code in ('STYLE-AI-DECLARATION-MISSING', 'STYLE-AI-DISCLOSURE-TOOL', 'STYLE-UNRESOLVED-MARKER',
                 'SUPPORT-DOI-MISSING', 'SUPPORT-STATUS-BEFORE-REVIEW', 'SUPPORT-BIB-VERSION'):
        assert code in joined
    assert 'leftover.tex' in joined and 'abstract has 300 words' in joined
    # Internal vocabulary is for a human decision, never a hard stop.
    assert 'STYLE-INTERNAL-AUDIT' not in joined


def test_stale_ledger_only_warns_in_internal_review(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from paper_writing import journal_history

    ledger = tmp_path / 'registry/journal-rejections.json'
    ledger.parent.mkdir(parents=True)
    ledger.write_text(json.dumps({'schema_version': journal_history.SCHEMA,
                                  'updated_at': (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
                                  'rejections': [], 'active_submissions': []}))
    monkeypatch.setattr(journal_history, '_policy', lambda root, policy=None: {
        'enabled': True, 'exclude_after_distinct_papers': 3, 'caution_after_distinct_papers': 2,
        'max_age_days': 7})
    paper = {'paper_id': 'p', 'target_journal': 'J'}
    with pytest.raises(ValueError, match='stale'):
        journal_history.guard_target(tmp_path, paper)
    pre = _formal_problem_preflight(tmp_path, monkeypatch, [], [], ledger=True)
    assert pre['blockers'] == []
    warning = next(a for a in pre['preparation_advisories'] if a['code'] == 'LEDGER-STALE')
    assert warning['kind'] == 'warning' and 'journal-history sync' in warning['message']
    # Outside the internal review (selection, retargeting, delivery) it is still an error.
    with pytest.raises(ValueError, match='stale'):
        journal_history.check_journal(tmp_path, 'J')



# --------------------------------------------------------------------------- formal verifier role (2026-11-11)

EDITOR_MODEL = {'provider': 'openai-codex', 'tool': 'Codex', 'model': 'gpt-6-astra'}
VERIFIER_MODEL = {'provider': 'openai-codex', 'tool': 'Codex', 'model': 'gpt-6.1-sol'}
REFEREE_MODEL = {'provider': 'anthropic', 'tool': 'Claude Code', 'model': 'claude-fable-5-2'}


@pytest.mark.parametrize('configured', [True, False])
def test_formal_stage_runs_on_formal_verifier_or_falls_back_to_editor(tmp_path, monkeypatch, configured):
    roles = {'editor': EDITOR_MODEL, 'referee_b': REFEREE_MODEL}
    if configured:
        roles['formal_verifier'] = VERIFIER_MODEL
    config = {'process': flow.PROCESS, 'roles': roles, 'referee_roles': ['referee_b'],
              'rejection_clearance_required': True, 'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    monkeypatch.setattr(flow, 'preflight', lambda *args: {
        'metadata': {'version': '1.0', 'target_journal': 'J'}, 'target': 'J', 'blockers': [],
        'fingerprints': {}, 'expanded': 'x', 'bibliography': ''})
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: [])
    used, model_roles = [], {}
    monkeypatch.setattr(flow.formal_checks, 'run_checks', lambda pre, root, run, role, timeout, runner:
                        used.append(('run', role)) or {'valid': True, 'blockers': []})
    monkeypatch.setattr(flow.formal_checks, 'validate_binding', lambda binding, metadata, root, role:
                        used.append(('validate', role)) or [])

    def run_role(**kw):
        model_roles[kw['role_name']] = kw['role']
        return ((editor(), {}) if kw['role_name'] == 'editor' else
                ({'letter': 'fixed'}, {}) if kw['role_name'] == 'decision_letter' else (referee('accept'), {}))
    monkeypatch.setattr(flow, 'run_role', run_role)
    record = flow.run_review('p', root=tmp_path, apply=False)
    expected = VERIFIER_MODEL if configured else EDITOR_MODEL
    assert used == [('run', expected), ('validate', expected)]
    assert record['formal_verifier_role'] == ('formal_verifier' if configured else 'editor')
    # The editorial screen and the decision letter stay on the editor's model.
    assert model_roles['editor'] == model_roles['decision_letter'] == EDITOR_MODEL


def test_formal_verifier_config_is_validated(monkeypatch):
    settings = {'review': {'roles': {'editor': EDITOR_MODEL, 'formal_verifier': dict(VERIFIER_MODEL)}}}
    monkeypatch.setattr(flow, 'load_registry_settings', lambda root: settings)
    assert flow.review_config('x')['roles']['formal_verifier'] == VERIFIER_MODEL
    settings['review']['roles']['formal_verifier'] = dict(REFEREE_MODEL)
    with pytest.raises(ValueError, match='Codex'):
        flow.review_config('x')
    settings['review']['roles']['formal_verifier'] = {'provider': 'openai-codex', 'model': 'gpt-6.1-sol'}
    with pytest.raises(ValueError, match='provider, tool and model'):
        flow.review_config('x')
    settings['review']['roles']['formal_verifier'] = dict(VERIFIER_MODEL, model='gpt 6.1 sol')
    with pytest.raises(ValueError, match='exact model identifier'):
        flow.review_config('x')


def _panel_config(roles, previous=()):
    return {'process': flow.PROCESS, 'roles': roles, 'referee_roles': ['referee_b'],
            'rejection_clearance_required': True, 'max_rounds_per_target': 10, 'timeout_seconds': 1,
            'previous_panels': list(previous)}


def test_records_without_formal_verifier_keep_editor_binding_and_policy_hash():
    old_roles = {'editor': EDITOR_MODEL, 'referee_b': REFEREE_MODEL}
    old = _panel_config(old_roles)
    old_hash = flow.review_policy_sha256(old)
    # Without the optional role, the policy and the bound role are what they were.
    assert flow.formal_role(old_roles) == EDITOR_MODEL and flow.formal_role_name(old_roles) == 'editor'
    new = _panel_config(dict(old_roles, formal_verifier=VERIFIER_MODEL), previous=[{
        'roles': old_roles, 'referee_roles': ['referee_b'],
        'valid_for_reviews_started_before': '2026-11-12T00:00:00+00:00'}])
    assert flow.review_policy_sha256(new) != old_hash
    earlier = {'started_at': '2026-11-10T08:00:00+00:00', 'active_referee_roles': ['referee_b']}
    policy = flow.policy_for_record(earlier, new)
    assert flow.review_policy_sha256(policy) == old_hash
    assert flow.formal_role(policy['roles']) == EDITOR_MODEL
    later = {'started_at': '2026-11-13T08:00:00+00:00', 'active_referee_roles': ['referee_b']}
    assert flow.formal_role(flow.policy_for_record(later, new)['roles']) == VERIFIER_MODEL


@pytest.mark.parametrize('started,expected', [('2026-11-10T08:00:00+00:00', 'editor'),
                                              ('2026-11-13T08:00:00+00:00', 'verifier')])
def test_apply_revalidates_formal_report_against_the_record_policy_role(tmp_path, monkeypatch, started, expected):
    meta, written = _apply_fixture(tmp_path, monkeypatch)
    old_roles = {'editor': EDITOR_MODEL, 'referee_b': REFEREE_MODEL}
    config = _panel_config(dict(old_roles, formal_verifier=VERIFIER_MODEL), previous=[{
        'roles': old_roles, 'referee_roles': ['referee_b'],
        'valid_for_reviews_started_before': '2026-11-12T00:00:00+00:00'}])
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    seen = []
    monkeypatch.setattr(flow.formal_checks, 'validate_binding',
                        lambda binding, metadata, root, role: seen.append(role) or [])
    record = {'paper_id': 'p', 'target_journal': 'J', 'manuscript_version': '1.0', 'started_at': started,
              'finished_at': started, 'active_referee_roles': ['referee_b'], 'round_for_target': 1,
              'review_policy_sha256': flow.review_policy_sha256(flow.policy_for_record(
                  {'started_at': started, 'active_referee_roles': ['referee_b']}, config)),
              'prior_decisions': [], 'editor_screen': editor(), 'referee_reports': {'referee_b': referee('accept')},
              'merged': flow.merge(editor(), {'referee_b': referee('accept')}), 'fingerprints': {},
              'formal_check': {'valid': True}}
    path = tmp_path / 'decision.json'
    path.write_text(json.dumps(record))
    release = flow.apply_decision('p', root=tmp_path, decision_path=path, digest=flow._sha256(path.read_bytes()))
    assert release['status'] == 'ready'
    assert seen == [EDITOR_MODEL if expected == 'editor' else VERIFIER_MODEL]


# --------------------------------------------------------------------------- unanimous referee reject (2026-11-11)

def _rejecting(blockers=(), significance=6, novelty=5, text='The advance over Lee (2023) is a new sample only.'):
    report = referee('reject', blockers=blockers)
    report['scores'] = {'clarity': 7, 'soundness': 6, 'significance': significance, 'novelty': novelty, 'overall': 4}
    report['significance'] = text
    report['novelty_and_context'] = 'Close to Lee (2023).'
    return report


@pytest.mark.parametrize('blockers_a,blockers_b', [((), ()), (('Lemma 2 is false',), ())])
def test_both_referees_reject_routes_to_direction_decision(blockers_a, blockers_b):
    screen = editor() | {'closest_prior_work': [{'work': 'Lee 2023', 'source': 'reference_list',
                                                 'known_result': 'Same estimator'}],
                         'advance_over_prior_work': 'A new county sample.'}
    merged = flow.merge(screen, {'referee_a': _rejecting(blockers_a, significance=3, novelty=2),
                                 'referee_b': _rejecting(blockers_b, significance=4, novelty=3)})
    assert merged['next_action'] == 'direction_decision'
    assert merged['outcome'] == 'revision_required' and merged['recommendation'] == 'reject'
    assert merged['recommendation_basis'] == 'all referees recommend reject'
    context = merged['direction_context']
    assert context['trigger'] == 'all_referees_reject'
    assert context['options'] == list(flow.DIRECTION_OPTIONS)
    assert context['closest_prior_work'][0]['work'] == 'Lee 2023'
    assert context['mean_significance_score'] == 3.5 and context['mean_novelty_score'] == 2.5
    rows = {r['referee']: r for r in context['referee_rejections']}
    assert rows['referee_a']['significance_score'] == 3 and rows['referee_b']['novelty_score'] == 3
    if blockers_a:
        assert rows['referee_a']['principal_reason'] == 'Lemma 2 is false'
        assert rows['referee_a']['principal_reason_source'] == 'scientific_blocker'
        assert merged['scientific_blockers'] == ['Lemma 2 is false']
    assert rows['referee_b']['principal_reason'].startswith('The advance over Lee')
    assert rows['referee_b']['principal_reason_source'] == 'significance_assessment'


def test_single_reject_keeps_the_existing_rule():
    split = flow.merge(editor(), {'referee_a': _rejecting(), 'referee_b': referee('minor_revision')})
    # An unsubstantiated lone reject: the more favourable recommendation stands.
    assert split['outcome'] == 'ready' and split['next_action'] is None and 'direction_context' not in split
    substantiated = flow.merge(editor(), {'referee_a': _rejecting(['Lemma 2 is false']),
                                          'referee_b': referee('accept')})
    assert substantiated['next_action'] == 'evidence_remediation' and 'direction_context' not in substantiated
    # A single-referee panel keeps the ordinary rule as well.
    alone = flow.merge(editor(), {'referee_b': _rejecting()})
    assert alone['next_action'] == 'evidence_remediation' and 'direction_context' not in alone


def test_unanimous_reject_is_applied_like_a_significance_desk_reject(tmp_path, monkeypatch):
    meta, written = _apply_fixture(tmp_path, monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {}, 'referee_roles': ['referee_a', 'referee_b'],
              'rejection_clearance_required': True, 'max_rounds_per_target': 10, 'previous_panels': []}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    referees = {'referee_a': _rejecting(), 'referee_b': _rejecting()}
    record = {'paper_id': 'p', 'target_journal': 'J', 'manuscript_version': '1.0',
              'finished_at': '2026-11-11T00:00:00Z', 'round_for_target': 1,
              'review_policy_sha256': flow.review_policy_sha256(config), 'prior_decisions': [],
              'editor_screen': editor(), 'referee_reports': referees,
              'merged': flow.merge(editor(), referees), 'fingerprints': {}}
    path = tmp_path / 'decision.json'
    path.write_text(json.dumps(record))
    release = flow.apply_decision('p', root=tmp_path, decision_path=path, digest=flow._sha256(path.read_bytes()))
    assert release['status'] == 'blocked' and release['next_action'] == 'direction_decision'
    assert release['direction_context']['trigger'] == 'all_referees_reject'
    assert release['decision'] == 'reject'


# --------------------------------------------------------------------------- unused declared routes (2026-11-11)

ROUTE_BODY = ('\\begin{document}\n\nFor real $x$, $x^2\\ge0$ by \\cite{mainref}.\n\n'
              r'\begin{thebibliography}{9}\bibitem{mainref}Main reference.\end{thebibliography}\end{document}')


def _route_workspace(tmp_path, formal_check):
    manuscript = tmp_path / 'papers/p/manuscript'
    manuscript.mkdir(parents=True)
    (manuscript / 'main.tex').write_text(ROUTE_BODY)
    evidence = tmp_path / 'papers/p/evidence/result.json'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"graphs": 12}')
    return {'paper_id': 'p', 'version': '1.0', 'manuscript_dir': 'papers/p/manuscript', 'target_journal': 'J',
            'target_journal_fit': {'status': 'approved'}, 'formal_check': formal_check}


STALE_ROUTES = {
    'sources': [{'reference_keys': ['mainref'], 'url': 'https://publisher.example/original',
                 'kind': 'primary_text', 'passage_patterns': ['Old selector text', 'For real']}],
    'local_evidence': [{'path': 'papers/p/evidence/result.json', 'sha256': '0' * 64,
                        'kind': 'execution_record', 'passage_patterns': ['Another old selector']}]}


def _route_preflight(tmp_path, monkeypatch, formal_check):
    from paper_writing import journal_history, manuscript_style, operations, support_citations

    metadata = _route_workspace(tmp_path, formal_check)
    pdf = tmp_path / 'built.pdf'
    pdf.write_bytes(b'%PDF-1.4 fixture')
    monkeypatch.setattr(flow, 'load_registry', lambda *args, **kwargs: None)
    monkeypatch.setattr(flow, 'load_paper_metadata', lambda *args, **kwargs: copy.deepcopy(metadata))
    monkeypatch.setattr(flow, '_build', lambda *args, **kwargs: (pdf, {'main.tex'}))
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style',
                        lambda *args, **kwargs: {'errors': [], 'blacklist_findings': [], 'notes': []})
    monkeypatch.setattr(support_citations, 'audit_manuscript_support', lambda *args, **kwargs: {'errors': []})
    monkeypatch.setattr(operations, '_review_workspace_fingerprints', lambda *args: {})
    monkeypatch.setattr(journal_history, 'guard_target', lambda *args, **kwargs: None)
    return metadata


def test_stale_selectors_and_local_evidence_are_advisories_and_the_review_continues(tmp_path, monkeypatch):
    _route_preflight(tmp_path, monkeypatch, copy.deepcopy(STALE_ROUTES))
    pre = flow.preflight('p', tmp_path, tmp_path / 'build')
    assert pre['blockers'] == []
    stale = [a for a in pre['preparation_advisories'] if a['code'] == 'SOURCE-SELECTOR-STALE']
    assert {a['location'] for a in stale} == {'https://publisher.example/original', 'papers/p/evidence/result.json'}
    message = next(a['message'] for a in stale if a['location'].startswith('https://'))
    assert "'Old selector text'" in message and 'https://publisher.example/original' in message
    assert all(a['kind'] == 'preparation' and a['source'] == 'formal_checks' for a in stale)
    unbound = next(a for a in pre['preparation_advisories'] if a['code'] == 'LOCAL-EVIDENCE-UNBOUND')
    assert 'hash mismatch' in unbound['message'] and unbound['location'] == 'papers/p/evidence/result.json'
    # The whole review proceeds: editor, referee, formal stage and a ready decision.
    mock_formal_stage(monkeypatch)
    config = {'process': flow.PROCESS, 'roles': {'editor': EDITOR_MODEL, 'referee_b': REFEREE_MODEL},
              'referee_roles': ['referee_b'], 'rejection_clearance_required': True,
              'timeout_seconds': 1, 'max_rounds_per_target': 10}
    monkeypatch.setattr(flow, 'review_config', lambda root: config)
    monkeypatch.setattr(flow, 'prior_decisions', lambda *args: [])
    monkeypatch.setattr(flow, 'run_role', lambda **kw: (
        (editor(), {}) if kw['role_name'] == 'editor' else
        ({'letter': 'fixed'}, {}) if kw['role_name'] == 'decision_letter' else (referee('accept'), {})))
    record = flow.run_review('p', root=tmp_path, apply=False)
    assert record['merged']['outcome'] == 'ready'
    assert {'SOURCE-SELECTOR-STALE', 'LOCAL-EVIDENCE-UNBOUND'} <= {a['code'] for a in record['preparation_advisories']}


def test_absent_bibliography_key_still_blocks_the_preflight(tmp_path, monkeypatch):
    routes = {'sources': [{'reference_keys': ['missingref'], 'url': 'https://publisher.example/original',
                           'kind': 'primary_text'}]}
    _route_preflight(tmp_path, monkeypatch, routes)
    pre = flow.preflight('p', tmp_path, tmp_path / 'build')
    assert pre['blockers'] == ['Source routing: https://publisher.example/original: absent bibliography key']
    assert not any(a['code'] == 'SOURCE-SELECTOR-STALE' for a in pre['preparation_advisories'])


def test_delivery_exit_only_notes_unused_routes(tmp_path, monkeypatch):
    from paper_writing import editorial_rewrite, manuscript_style, registry, support_citations

    metadata = _route_workspace(tmp_path, copy.deepcopy(STALE_ROUTES))
    monkeypatch.setattr(registry, 'load_registry_settings', lambda *args, **kwargs: {})
    monkeypatch.setattr(manuscript_style, 'audit_manuscript_style',
                        lambda *args, **kwargs: {'errors': [], 'blacklist_findings': []})
    monkeypatch.setattr(support_citations, 'audit_manuscript_support', lambda *args, **kwargs: {'errors': []})
    monkeypatch.setattr(editorial_rewrite, 'abstract_findings', lambda *args: [])
    notes = []
    assert flow.delivery_blockers('p', metadata, tmp_path, {'build_inputs': ['main.tex']}, notes=notes) == []
    stale = [n for n in notes if n['kind'] == 'stale_registration_route']
    assert {(n['code'], n['route']) for n in stale} == {
        ('SOURCE-SELECTOR-STALE', 'https://publisher.example/original'),
        ('SOURCE-SELECTOR-STALE', 'papers/p/evidence/result.json'),
        ('LOCAL-EVIDENCE-UNBOUND', 'papers/p/evidence/result.json')}
    assert next(n for n in stale if n.get('selector') == 'Old selector text')['route_kind'] == 'stale_selector'


def _fake_claude_stream(tmp_path, monkeypatch, reported_model, *, rate_limit=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    events = [{"type": "system", "subtype": "init", "model": reported_model}]
    if rate_limit:
        events.append({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
            "five_hour": {"utilization": 0.25, "resetsAt": 1_800_000_000},
            "seven_day_overage_included": {"utilization": 0.5, "resetsAt": 1_800_000_000}}}})
    events.append({"type": "result", "subtype": "success", "is_error": False,
                   "structured_output": {"answer": "ok"}, "modelUsage": {reported_model: {}}})
    stream = "\n".join(json.dumps(e) for e in events)
    script = bin_dir / "claude"
    script.write_text("#!/bin/sh\ncat >/dev/null\ncat <<'JSON'\n" + stream + "\nJSON\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_launcher_reads_stream_json_and_records_the_quota_reading(tmp_path, monkeypatch):
    _fake_claude_stream(tmp_path, monkeypatch, "claude-fable-5-2")
    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    result, receipt = run_role(role_name="referee_a", role={"provider": "anthropic", "tool": "Claude Code",
                                                            "model": "claude-fable-5-2"},
                               system_prompt="sys", user_prompt="hello", schema=schema, workdir=tmp_path / "run")
    # The result, the hashes and the receipt fields mean what they meant with --output-format json.
    assert result == {"answer": "ok"}
    assert json.loads((tmp_path / "run" / "output.json").read_text()) == {"answer": "ok"}
    assert receipt["output_sha256"] == hashlib.sha256((tmp_path / "run" / "output.json").read_bytes()).hexdigest()
    assert receipt["prompt_sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert "stream-json" in receipt["command"] and "--verbose" in receipt["command"]
    assert "quota" not in json.dumps(receipt)
    quota = json.loads((tmp_path / "run" / "quota.json").read_text())
    assert quota["schema_version"] == "openlabs.quota_snapshot.v1" and quota["provider"] == "anthropic"
    assert quota["model"] == "claude-fable-5-2" and quota["role"] == "referee_a"
    windows = {w["name"]: w for w in quota["windows"]}
    assert windows["five_hour"]["used_fraction"] == 0.25 and windows["five_hour"]["window_minutes"] == 300
    assert windows["seven_day_overage_included"]["window_minutes"] == 10_080


def test_launcher_without_a_rate_limit_event_writes_no_quota_file(tmp_path, monkeypatch):
    _fake_claude_stream(tmp_path, monkeypatch, "claude-opus-5-5", rate_limit=False)
    result, _ = run_role(role_name="referee_a", role={"provider": "anthropic", "tool": "Claude Code",
                                                      "model": "claude-opus-5-5"},
                         system_prompt="s", user_prompt="u", schema={"type": "object"}, workdir=tmp_path / "run")
    assert result == {"answer": "ok"} and not (tmp_path / "run" / "quota.json").exists()


def test_stream_without_a_result_event_is_rejected():
    from paper_writing.review_launcher import parse_claude_stream

    with pytest.raises(LaunchError, match="no final result"):
        parse_claude_stream(json.dumps({"type": "system"}) + "\n" + json.dumps({"type": "assistant"}))
