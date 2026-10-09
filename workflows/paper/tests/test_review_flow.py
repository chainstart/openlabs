import hashlib
import json
import os
import stat

import pytest

from paper_writing import review_flow as flow
from paper_writing.review_launcher import LaunchError, _validate_against_schema, role_runtime, run_role


def editor(decision="send_to_review", category="none"):
    return {"decision": decision, "desk_reject_category": category}


def referee(rec="minor_revision", blockers=(), changes=(), previous=()):
    return {"recommendation": rec, "scientific_blockers": list(blockers),
            "required_changes": [{"change": c, "type": t, "location": "S1"} for c, t in changes],
            "previous_items": list(previous), "scores": {"overall": 6}}


@pytest.mark.parametrize("decision,category,action", [
    ("revise_before_submission", "presentation", "text_revision"),
    ("desk_reject", "presentation", "text_revision"),
    ("desk_reject", "scope", "retarget_required"),
    ("desk_reject", "readership", "retarget_required"),
    ("desk_reject", "significance", "evidence_remediation"),
    ("desk_reject", "incremental", "evidence_remediation"),
])
def test_editor_screen_stops_before_referees(decision, category, action):
    merged = flow.merge(editor(decision, category), {})
    assert merged["outcome"] == decision and merged["next_action"] == action


def test_more_cautious_referee_prevails():
    merged = flow.merge(editor(), {"referee_a": referee("accept"), "referee_b": referee("major_revision")})
    assert merged["recommendation"] == "major_revision" and merged["outcome"] == "revision_required"


def test_editor_revision_requests_remain_mandatory_but_desk_suggestions_do_not():
    screen = editor("revise_before_submission", "presentation") | {"presentation_problems": ["Define the main object before the theorem."]}
    changes = flow.merge(screen, {})["required_changes"]
    assert changes[0]["type"] == "text" and changes[0]["referee"] == "editor"
    rejected = screen | {"decision": "desk_reject", "desk_reject_category": "significance"}
    assert flow.merge(rejected, {})["required_changes"] == []


def test_previous_editor_revision_recovers_legacy_missing_mandatory_items(tmp_path):
    run = tmp_path / "reviews/unified/example/20260101T000000Z"
    run.mkdir(parents=True)
    (run / "manuscript-expanded.tex").write_text("old text")
    record = {"stage_reached": "decision", "target_journal": "Journal", "merged": {"required_changes": []},
              "editor_screen": {"decision": "revise_before_submission", "presentation_problems": ["Define X."]}}
    (run / "decision.json").write_text(json.dumps(record))
    previous = flow._previous_round(tmp_path, "example", "Journal", "new text", "X is now defined.")
    assert previous["items"] == ["[text] Define X. (Editor screen: manuscript presentation)"]
    record["editor_screen"]["decision"] = "desk_reject"
    (run / "decision.json").write_text(json.dumps(record))
    assert flow._previous_round(tmp_path, "example", "Journal", "new text", "response")["items"] == []


def test_ready_only_with_text_changes_and_no_blockers():
    ready = flow.merge(editor(), {"referee_a": referee("accept"),
                                  "referee_b": referee("minor_revision", changes=[("typo", "text")])})
    assert ready["outcome"] == "ready" and ready["next_action"] is None
    narrowing = flow.merge(editor(), {"referee_a": referee("accept"),
                                      "referee_b": referee("minor_revision", changes=[("weaken", "claim_narrowing")])})
    assert narrowing["outcome"] == "revision_required" and narrowing["next_action"] == "text_revision"
    blocked = flow.merge(editor(), {"referee_a": referee("accept", blockers=["gap in Lemma 2"]),
                                    "referee_b": referee("accept")})
    assert blocked["outcome"] == "revision_required" and blocked["next_action"] == "evidence_remediation"
    assert blocked["scientific_blockers"] == ["gap in Lemma 2"]


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
    monkeypatch.setattr(flow, '_target_block', lambda metadata: 'Journal')
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
