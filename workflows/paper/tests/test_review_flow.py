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


def test_unused_source_files_are_reported(tmp_path):
    for name in ("main.tex", "used.tex", "old.tex", "notes.md", "references.bib"):
        (tmp_path / name).write_text("x")
    assert flow.unused_source_files(tmp_path, {"used.tex", "references.bib"}) == ["old.tex"]
    assert flow.unused_source_files(tmp_path, {"used.tex"}) == ["old.tex"]


def test_unified_release_validation(tmp_path):
    record = {"merged": {"outcome": "ready"}, "editor_screen": {"decision": "send_to_review"},
              "fingerprints": {"manuscript_snapshot_sha256": "a" * 64}, "target_journal": "J"}
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
