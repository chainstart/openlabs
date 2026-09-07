"""Offline editorial-gate acceptance and adversarial tests; no model is called."""
import importlib.util
import json
from pathlib import Path

import pytest

from paper_writing import review_delta as delta
from paper_writing.handoff import _release_paths, HandoffError
from paper_writing.operations import create_paper, start_revision
from paper_writing.registry import load_paper_metadata, write_paper_metadata
from test_review import _review, AGGREGATOR

PID = "20260907-math-graph-delta-test"


@pytest.fixture
def paper(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    (root / "registry").mkdir()
    (root / "registry/settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\nquality_gate:\n"
        "  maximum_revision_rounds: 3\n  minimum_score: 5\n"
        "  review_panel_size: 1\n  decision_standard: cas_zone_1_journal\n"
        "  cas_zone_1_minimum_decision: minor_revision\n"
        "  incremental_review:\n    enabled: true\n    scope: editorial_only\n")
    create_paper(paper_id=PID, title="Editorial delta test", created_at="2026-09-07",
        domain="math", subdomain="graph", venue_type="journal", root=root)
    metadata = load_paper_metadata(PID, root)
    manuscript = root / metadata["manuscript_dir"]
    (manuscript / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nEvery graph has the stated property.\n\\begin{theorem}For every $q$, the claim holds.\\end{theorem}\n\\begin{proof}The identity gives $x=1$.\\end{proof}\n\\end{document}\n")
    (manuscript / "main.pdf").write_bytes(b"%PDF offline test fixture")
    metadata["latest_pdf"] = str((manuscript / "main.pdf").relative_to(root))
    write_paper_metadata(PID, metadata, root)
    _, fingerprints = delta.workspace(PID, metadata, root)
    raw = _review(paper_id=PID, role="math")
    raw["scores"]["overall"] = 6
    raw["recommendations"]["cas_zone_1_journal"]["decision"] = "minor_revision"
    raw["publishability_summary"] = {"scientific_ready": True, "text_ready": False, "blocking_reason": "Add citation."}
    raw["unresolved_blockers"] = []
    raw["required_changes"] = ["Add citation."]
    raw["change_requests"] = [{"request": "Add citation.", "category": "text_only", "priority": "low",
        "targets": ["main.tex"], "rationale": "Attribution", "text_only": True}]
    raw["review_metadata"].update(provider="openai-codex", model="offline-test", panel_reviewer_id="reviewer-1",
        independent_context=True, isolated_process=True, prior_reviews_hidden=True,
        main_tex_sha256=delta.digest((manuscript / "main.tex").read_bytes()),
        manuscript_snapshot_sha256_before=fingerprints["manuscript_snapshot_sha256"],
        manuscript_snapshot_sha256_after=fingerprints["manuscript_snapshot_sha256"])
    directory = root / "reviews/full" / PID
    directory.mkdir(parents=True)
    (directory / "reviewer-1.json").write_bytes(delta.encoded(raw))
    spec = importlib.util.spec_from_file_location("delta_test_aggregate", AGGREGATOR)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.main(["--paper-id", PID, "--review-dir", str(directory), "--root", str(root)]) == 0
    metadata["ara_llm_self_review"] = {"source": str((directory / "review.json").relative_to(root))}
    metadata["writing_release"] = {"status": "revision_required", "manuscript_version": metadata["version"],
        "revision_rounds_completed": 1, **fingerprints}
    write_paper_metadata(PID, metadata, root)
    # These tests exercise review provenance/scope, not the existing style and support auditors.
    monkeypatch.setattr(delta, "deterministic_checks", lambda *args: None)
    return root, manuscript


def revise(paper):
    root, manuscript = paper
    result = start_revision(PID, "Add requested citation", root=root)
    assert result["delta_baseline_available"], result
    source = manuscript / "main.tex"
    source.write_text(source.read_text().replace("stated property.", "stated property~\\cite{Source}."))
    (manuscript / "main.pdf").write_bytes(b"%PDF updated offline test fixture")
    return delta.prepare_delta(PID, root=root)


def receipt(root, prepared, *, verdict="resolved", blockers=()):
    packet = prepared["packet"]
    result = {"schema_version": delta.RESULT, "packet_sha256": prepared["binding"]["sha256"],
        "verdict": verdict, "scientific_content_unchanged": verdict != "escalate",
        "changes": [{"path": row["path"], "status": "resolved", "evidence": "Offline citation fixture checked."} for row in packet["changes"]],
        "issues": [{"id": row["id"], "status": "resolved", "evidence": "Offline issue checked."} for row in packet["issues"]],
        "new_blockers": list(blockers), "optional_suggestions": ["Optionally shorten prose."],
        "build_check": {"status": "PASS", "evidence": "Offline fixture, no real PDF build."},
        "visual_check": {"status": "PASS", "evidence": "Offline fixture, no real visual review."}}
    directory = root / "reviews/delta-test" / str(len(packet["history"]))
    directory.mkdir(parents=True)
    (directory / "output.json").write_bytes(delta.encoded(result))
    for name in ("prompt", "events", "stderr"):
        (directory / name).write_text("offline fixture")
    (directory / "inputs").mkdir()
    reviewer_input = {key: packet[key] for key in ("paper_id", "version", "changes", "issues")}
    reviewer_input["packet_sha256"] = prepared["binding"]["sha256"]
    (directory / "inputs/delta.json").write_bytes(delta.encoded(reviewer_input))
    baseline = delta.read(root / packet["baseline"]["path"])
    content, _ = delta.workspace(PID, load_paper_metadata(PID, root), root)
    for side, values in (("old", delta.decode_sources(baseline)), ("new", content)):
        for name, value in values.items():
            if Path(name).suffix in delta.CONTEXT_SUFFIXES:
                target = directory / "inputs" / side / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
    canonical = directory / "canonical.pdf"
    canonical.write_bytes((root / f"papers/{PID}/manuscript/main.pdf").read_bytes())
    build = delta.save({"schema_version": "openlabs.paper_writing.delta_build.v1", "status": "PASS",
        "snapshot_sha256": packet["fingerprints"]["manuscript_snapshot_sha256"], "exit_code": 0,
        "canonical_text_matches_clean_build": True, "log": delta.binding(directory / "events", root),
        "canonical_pdf": delta.binding(canonical, root), "rebuilt_pdf": delta.binding(canonical, root)}, directory, root)
    record = {"schema_version": delta.RECEIPT, "packet": prepared["binding"],
        "output": delta.binding(directory / "output.json", root), "exit_code": 0,
        "ephemeral": True, "author_conversation_supplied": False, "prior_scores_supplied": False,
        "prior_issue_list_supplied": True, "command": ["codex", "exec", "--ephemeral"],
        "model": "offline-test", "snapshot_before": packet["fingerprints"]["manuscript_snapshot_sha256"],
        "build": build, "inputs_unchanged": True,
        "input_hashes": {p.relative_to(directory / "inputs").as_posix(): delta.digest(p.read_bytes()) for p in (directory / "inputs").rglob("*") if p.is_file()},
        "snapshot_after": packet["fingerprints"]["manuscript_snapshot_sha256"],
        **{name: delta.binding(directory / name, root) for name in ("prompt", "events", "stderr")}}
    return delta.save(record, directory, root)


def test_citation_delta_from_scientifically_ready_nonpassing_gate(paper):
    root, manuscript = paper
    prepared = revise(paper)
    old_projection = load_paper_metadata(PID, root)["ara_llm_self_review"]
    item = receipt(root, prepared)
    applied = delta.apply_delta(PID, receipt=item["path"], root=root)
    assert applied["passed"] and applied["scores_changed"] is False
    metadata = load_paper_metadata(PID, root)
    assert metadata["ara_llm_self_review"] == old_projection
    assert metadata["writing_release"]["score"] == 6
    assert metadata["writing_release"]["revision_rounds_completed"] == 2
    assert _release_paths(PID, root, metadata)[2]
    # Optional suggestions are not release blockers.
    assert metadata["writing_release"]["status"] == "ready"
    (manuscript / "main.tex").write_text("changed after review")
    with pytest.raises(HandoffError):
        _release_paths(PID, root, load_paper_metadata(PID, root))


@pytest.mark.parametrize("before,after", [
    ("Every graph", "Some graph"), ("$x=1$", "$x=2$"),
    ("The identity gives", "A different argument gives"),
    ("\\documentclass{article}", "\\documentclass{book}"),
])
def test_scientific_and_global_changes_escalate(paper, before, after):
    root, manuscript = paper
    revise(paper)
    source = manuscript / "main.tex"
    source.write_text(source.read_text().replace(before, after))
    assert delta.route_review(PID, root=root)["route"] == "full"


def test_cumulative_chain_budget_and_new_blockers(paper):
    root, manuscript = paper
    first = revise(paper)
    item = receipt(root, first, verdict="unresolved", blockers=["Clarify attribution."])
    assert not delta.apply_delta(PID, receipt=item["path"], root=root)["passed"]
    assert start_revision(PID, "Clarify attribution", root=root)["delta_baseline_available"]
    source = manuscript / "main.tex"
    source.write_text(source.read_text().replace("stated property", "stated, attributed property"))
    second = delta.prepare_delta(PID, root=root)
    assert "delta:0:0" in [i["id"] for i in second["packet"]["issues"]]
    assert "cite{Source}" in second["packet"]["changes"][0]["diff"]
    item = receipt(root, second)
    assert delta.apply_delta(PID, receipt=item["path"], root=root)["passed"]
    assert start_revision(PID, "Another edit", root=root)["delta_baseline_available"]
    assert delta.route_review(PID, root=root)["route"] == "blocked"


def test_omitted_diff_and_forged_runtime_rejected(paper):
    root, _ = paper
    prepared = revise(paper)
    prepared["packet"]["changes"] = []
    prepared["binding"] = delta.save(prepared["packet"], root / "reviews/forged", root)
    item = receipt(root, prepared)
    with pytest.raises(ValueError, match="complete delta"):
        delta.apply_delta(PID, receipt=item["path"], root=root)
    record = delta.read(root / item["path"])
    record["command"] = ["codex", "exec", "resume", "--ephemeral"]
    forged = delta.save(record, root / "reviews/forged-runtime", root)
    with pytest.raises(ValueError, match="fresh runtime"):
        delta.validate_receipt(forged, root)


def test_added_file_policy_and_raw_review_tampering(paper):
    root, manuscript = paper
    revise(paper)
    added = manuscript / "data.csv"
    added.write_text("changed scientific data")
    assert delta.route_review(PID, root=root)["route"] == "full"
    added.unlink()
    raw = root / "reviews/full" / PID / "reviewer-1.json"
    raw.write_text(raw.read_text() + " ")
    assert delta.route_review(PID, root=root)["route"] == "full"


def test_dp_three_citation_hunks_are_within_syntactic_scope():
    old = {
        "introduction.tex": b"The list color function eventually equals the chromatic polynomial,\n",
        "explicit-example.tex": b"\\begin{proposition}A formula.\\end{proposition}\n",
        "prime-periods.tex": b"\\begin{lemma}A count.\\end{lemma}\n",
    }
    new = {
        "introduction.tex": b"The list color function eventually equals the chromatic\npolynomial~\\cite[Corollary~2]{DZ2023},\n",
        "explicit-example.tex": b"The following formula specializes Zaslavsky's fixed-set expansion\n\\cite[Theorem~3.6]{Zaslavsky2009} to the involution action.\n\n" + old["explicit-example.tex"],
        "prime-periods.tex": b"The counting formula below is the prime-cyclic specialization of\nZaslavsky's fixed-set expansion and orbit-multiplicity polynomial\n\\cite[Theorems~3.6 and~4.1]{Zaslavsky2009}.\n\n" + old["prime-periods.tex"],
    }
    assert delta.scope_reasons(old, new) == []


def test_unchanged_external_or_dynamic_input_cannot_reuse_review():
    assert delta.dependency_reasons({"main.tex": b"\\input{../unbound-proof.tex}"})
    assert delta.dependency_reasons({"main.tex": b"\\input \\dynamicfile"})
    assert not delta.dependency_reasons({"main.tex": b"\\input{proof}", "proof.tex": b"A fixed proof."})


@pytest.mark.parametrize("mutation", ["metadata", "policy", "context", "build", "score"])
def test_release_replays_all_bindings(paper, mutation):
    root, _ = paper
    prepared = revise(paper)
    item = receipt(root, prepared)
    delta.apply_delta(PID, receipt=item["path"], root=root)
    metadata = load_paper_metadata(PID, root)
    if mutation == "metadata":
        metadata["keywords"] = ["different claim"]
    elif mutation == "policy":
        path = root / "registry/settings.yaml"
        path.write_text(path.read_text().replace("minimum_score: 5", "minimum_score: 7"))
    elif mutation == "context":
        record = delta.read(root / item["path"])
        path = (root / record["prompt"]["path"]).parent / "inputs/new/main.tex"
        path.write_text("context replaced")
    elif mutation == "build":
        record = delta.read(root / item["path"])
        (root / record["build"]["path"]).write_text("{}")
    else:
        metadata["writing_release"]["score"] = 9
    write_paper_metadata(PID, metadata, root)
    with pytest.raises(HandoffError):
        _release_paths(PID, root, load_paper_metadata(PID, root))


def test_prior_scientific_escalation_cannot_be_closed_by_next_delta(paper):
    root, _ = paper
    prepared = revise(paper)
    item = receipt(root, prepared, verdict="escalate", blockers=["A central premise requires review."])
    assert not delta.apply_delta(PID, receipt=item["path"], root=root)["passed"]
    start_revision(PID, "Attempt editorial closeout", root=root)
    assert delta.route_review(PID, root=root)["route"] == "full"


def test_fresh_runner_end_to_end_with_explicitly_mocked_model(paper, monkeypatch):
    from paper_writing import review_delta_runner as runner
    root, _ = paper
    prepared = revise(paper)
    fixture = receipt(root, prepared)
    fixture_record = delta.read(root / fixture["path"])
    result = delta.read(root / fixture_record["output"]["path"])
    monkeypatch.setattr(runner, "clean_build", lambda *args: fixture_record["build"])
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))

    class ModelFixture:
        pid = 123
        returncode = 0

        def __init__(self, cmd, **kwargs):
            calls.append(cmd)
            self.output = Path(cmd[cmd.index("-o") + 1])

        def communicate(self, prompt=None, timeout=None):
            assert b"cumulative change" in prompt
            self.output.write_bytes(delta.encoded(result))

    monkeypatch.setattr(runner.subprocess, "Popen", ModelFixture)
    response = runner.run_delta(PID, root=root, model="explicit-offline-fixture")
    cmd = calls[-1]
    assert "--ephemeral" in cmd and "--ignore-user-config" in cmd and "resume" not in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert response["verdict"] == "resolved" and response["applied"] is False
    applied = delta.apply_delta(PID, receipt=response["receipt"]["path"], root=root)
    assert applied["passed"]


def test_real_clean_build_checks_canonical_pdf_freshness(tmp_path):
    import shutil
    import subprocess
    from paper_writing.review_delta_runner import clean_build
    if not all(shutil.which(tool) for tool in ("latexmk", "pdftotext")):
        pytest.skip("TeX toolchain not installed")
    source = b"\\documentclass{article}\n\\begin{document}A citation check.\\end{document}\n"
    stage = tmp_path / "initial"
    stage.mkdir()
    (stage / "main.tex").write_bytes(source)
    subprocess.run(["latexmk", "-pdf", "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
        cwd=stage, check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    content = {"main.tex": source, "main.pdf": (stage / "main.pdf").read_bytes()}
    packet = {"fingerprints": {"manuscript_snapshot_sha256": delta.snapshot(content)}}
    good = tmp_path / "good"
    good.mkdir()
    assert delta.read(tmp_path / clean_build(content, good, tmp_path, packet)["path"])["status"] == "PASS"
    content["main.tex"] = source.replace(b"citation", b"different")
    bad = tmp_path / "bad"
    bad.mkdir()
    with pytest.raises(ValueError, match="canonical PDF text differs"):
        clean_build(content, bad, tmp_path, packet)
