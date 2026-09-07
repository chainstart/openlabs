"""Offline closeout contract tests; no paper data, models or network are used."""
import importlib.util
import json
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from paper_writing import minor_closeout as closeout
from paper_writing.handoff import (HandoffError, _release_paths, _source_files,
                                  manuscript_snapshot_sha256, validate_release_preconditions)
from paper_writing.operations import create_paper
from paper_writing.registry import load_paper_metadata, write_paper_metadata
from paper_writing.support import build_support_archive
from test_review import _review, AGGREGATOR


PID = "20260901-math-combinatorics-minor-closeout-test"
VENUE = ("Four-leading-journal suitability: exceptional depth is not established. "
         "This is a venue-level limitation, not an unresolved correctness gap.")
VENUE_REQUEST = ("For reconsideration at the four-leading-journal standard, establish broader consequences. "
                 "This is a venue-specific requirement, not a repair needed for the stated theorem.")
VENUE_REQUIRED = ("For four-leading-journal reconsideration only, supply broader consequences. "
                  "No mandatory scientific repair is identified for ordinary publication of the stated results.")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def archive(path, members):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as out:
        for name, value in members.items():
            out.writestr(name, value)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "openlabs-data"
    root.mkdir()
    settings = root / "registry/settings.yaml"
    settings.parent.mkdir()
    settings.write_text("schema_version: ara.paper_writing.registry.v1\nquality_gate:\n"
                        "  maximum_revision_rounds: 12\n  minimum_score: 5\n"
                        "  decision_standard: cas_zone_1_journal\n  cas_zone_1_minimum_decision: minor_revision\n")
    create_paper(paper_id=PID, title="A bounded test", created_at="2026-09-01",
                 domain="math", subdomain="combinatorics", venue_type="journal", root=root)
    metadata = load_paper_metadata(PID, root)
    manuscript = root / metadata["manuscript_dir"]
    pdf = manuscript / "main.pdf"
    pdf.write_bytes(b"%PDF-1.4 frozen offline fixture")
    metadata["latest_pdf"] = str(pdf.relative_to(root))
    support_dir = root / f"papers/{PID}/support-materials/public-support-v0.1.0"
    support_dir.mkdir()
    (support_dir / "science.py").write_text("# frozen science\n")
    (support_dir / "CLAIMS.yaml").write_text("version: 0.1.0\nclaim: unchanged\n")
    metadata["support"]["publication"].update(license="cc-by-4.0", source_files=[str(support_dir.relative_to(root))])
    support = build_support_archive(metadata, list(support_dir.iterdir()), repo_root=root, origin_commit="a" * 40)
    support_path = support["archive"]
    metadata["support"]["publication"]["package_sha256"] = closeout._sha(support_path)
    source_path = root / f"papers/{PID}/production/source.zip"
    archive(source_path, {p.relative_to(manuscript).as_posix(): p.read_bytes()
                          for p in _source_files(manuscript, pdf)})
    metadata["submission_package"] = {"status": "built", "version": "0.1.0", "source_archive": str(source_path.relative_to(root)),
                                      "source_archive_sha256": closeout._sha(source_path)}
    snapshot = manuscript_snapshot_sha256(manuscript, pdf)
    raw = _review(paper_id=PID, role="math")
    raw["scores"]["overall"] = 6
    raw["recommendations"]["cas_zone_1_journal"]["decision"] = "minor_revision"
    raw["publishability_summary"] = {"scientific_ready": True, "text_ready": False, "blocking_reason": "Text correction remains."}
    raw["unresolved_blockers"] = [VENUE]
    raw["required_changes"] = ["Clarify the notation."]
    raw["change_requests"] = [{"request": "Clarify the notation.", "category": "proof_exposition", "priority": "low",
                               "targets": ["main.tex"], "rationale": "Ambiguous notation.", "text_only": True}]
    raw["review_metadata"].update(provider="openai-codex", model="gpt-6-astra", panel_reviewer_id="reviewer-1",
        independent_context=True, isolated_process=True, prior_reviews_hidden=True,
        main_tex_sha256=closeout._sha(manuscript / "main.tex"), manuscript_snapshot_sha256_before=snapshot,
        manuscript_snapshot_sha256_after=snapshot)
    review_dir = root / "reviews/fresh" / PID
    raw_path = review_dir / "reviewer-1.json"
    write(raw_path, raw)
    metadata["ara_llm_self_review"] = {"source": str((review_dir / "review.json").relative_to(root)),
                                      "scores": deepcopy(raw["scores"]), "manuscript_snapshot_sha256": snapshot}
    metadata["writing_release"] = {"status": "blocked", "revision_rounds_completed": 12}
    write_paper_metadata(PID, metadata, root)
    spec = importlib.util.spec_from_file_location("test_closeout_aggregator", AGGREGATOR)
    aggregator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(aggregator)
    assert aggregator.main(["--paper-id", PID, "--review-dir", str(review_dir), "--root", str(root)]) == 0
    write(review_dir / "apply-cli.json", {"quality_gate": {"paper_id": PID, "score": 6, "decision": "minor_revision",
          "revision_rounds": 12, "manuscript_snapshot_sha256": snapshot, "status": "blocked"}})
    run = "offline-review/" + PID
    art = root.parent / "openlabs-artifacts" / run
    packet = art / "packet"
    packet.mkdir(parents=True)
    (packet / "source.zip").write_bytes(source_path.read_bytes())
    (packet / "support.zip").write_bytes(support_path.read_bytes())
    (packet / "main.pdf").write_bytes(pdf.read_bytes())
    binding = {"paper_id": PID, "version": "0.1.0", "manuscript_snapshot_sha256": snapshot,
               "source_archive_sha256": closeout._sha(source_path), "support_package_sha256": closeout._sha(support_path),
               "canonical_pdf_sha256": closeout._sha(pdf)}
    write(packet / "input-binding.json", binding)
    write(art / "snapshot.json", {**binding, "packet_sha256": "b" * 64})
    write(art / "postvalidation.json", {"valid": True, "errors": [], "packet_sha256": "b" * 64,
                                       "review_sha256": closeout._sha(raw_path)})
    auth_path = root / "registry/quality-gate-exceptions/closeout.json"
    auth = {"schema_version": closeout.AUTH_SCHEMA, "scope": closeout.SCOPE, "actor": "user", "confirmed": True,
            "confirmed_at": "2020-01-01T00:00:00+00:00", "source": "Explicit test user authorization", "quote": "Close this paper's text requests.",
            "minimum_score": 5, "decision_standard": "cas_zone_1_journal", "minimum_decision": "minor_revision",
            "papers": {PID: {"source_version": "0.1.0", "target_version": "0.1.0", "source_review_sha256": closeout._sha(raw_path),
                             "venue_suitability_blockers": [VENUE], "venue_suitability_change_requests": [],
                             "venue_suitability_required_changes": [], "optional_not_required_change_requests": []}}}
    write(auth_path, auth)
    # These have separate full suites; isolate author-side closeout contract here.
    monkeypatch.setattr("paper_writing.manuscript_style.audit_manuscript_style", lambda *a, **kw: {"valid": True, "errors": []})
    monkeypatch.setattr("paper_writing.support_citations.audit_manuscript_support", lambda *a, **kw: {"valid": True, "errors": []})
    return {"root": root, "metadata": metadata, "raw_path": raw_path, "raw": raw, "art": art,
            "auth_path": auth_path, "auth": auth, "run": run, "support_path": support_path, "pdf": pdf,
            "source_path": source_path, "manuscript": manuscript, "review_dir": review_dir, "aggregator": aggregator}


def prepare(b):
    return closeout.inspect_minor_closeout(PID, authorization=str(b["auth_path"].relative_to(b["root"])),
        source_run=b["run"], support_archive=str(b["support_path"].relative_to(b["root"])), root=b["root"])


def certificate(b):
    c = prepare(b)
    proof = b["root"] / "maintenance/closeout/evidence.md"
    proof.parent.mkdir(parents=True, exist_ok=True)
    proof.write_text("Author-side fixture: checked this exact delta, PDF, build and unchanged science; not an independent review.")
    evidence = {"path": str(proof.relative_to(b["root"])), "sha256": closeout._sha(proof)}
    for field in ("request_resolutions", "required_change_resolutions", "delta_resolutions"):
        for row in c[field]:
            row["reason" if field == "delta_resolutions" else "resolution"] = "Checked explicitly in the bound evidence."
            row["evidence"] = evidence
    for row in c["checks"]:
        row.update(status="PASS", evidence=evidence)
    c.update(verified_at="2020-01-02T00:00:00+00:00", verified_by="Author-side test coordinator")
    path = b["root"] / "maintenance/closeout/certificate.json"
    write(path, c)
    return path, c


def test_closeout_preserves_original_review_scores_and_rounds_and_freezes_evidence(bundle):
    b = bundle
    path, c = certificate(b)
    old_raw = b["raw_path"].read_bytes()
    old_panel = (b["review_dir"] / "review.json").read_bytes()
    old_projection = load_paper_metadata(PID, b["root"])["ara_llm_self_review"]
    result = closeout.apply_minor_closeout(PID, certificate=str(path.relative_to(b["root"])), root=b["root"])
    assert result["passed"] and result["rounds_added"] == 0 and not result["new_independent_review"]
    current = load_paper_metadata(PID, b["root"])
    assert current["ara_llm_self_review"] == old_projection
    assert current["writing_release"]["revision_rounds_completed"] == 12
    assert current["writing_release"]["nonblocking_venue_findings"] == [VENUE]
    assert b["raw_path"].read_bytes() == old_raw
    assert (b["review_dir"] / "review.json").read_bytes() == old_panel
    _, _, files = _release_paths(PID, b["root"], current)
    assert path in files and b["auth_path"] in files and b["root"] / "maintenance/closeout/evidence.md" in files


@pytest.mark.parametrize("field", ["schema_version", "paper_id", "source_version", "revision_rounds_completed", "source_run"])
def test_certificate_cannot_relabel_identity_or_rounds(bundle, field):
    path, c = certificate(bundle)
    c[field] = "tampered"
    write(path, c)
    with pytest.raises((ValueError, FileNotFoundError)):
        closeout.validate_minor_closeout(PID, str(path.relative_to(bundle["root"])), root=bundle["root"])


@pytest.mark.parametrize("field", ["request_resolutions", "required_change_resolutions", "checks"])
def test_missing_closeout_requests_or_checks_fail(bundle, field):
    path, c = certificate(bundle)
    c[field] = []
    write(path, c)
    with pytest.raises(ValueError):
        closeout.validate_minor_closeout(PID, str(path.relative_to(bundle["root"])), root=bundle["root"])


@pytest.mark.parametrize("target", ["pdf", "auth_path", "raw_path", "source_path", "support_path"])
def test_changed_inputs_fail_closed(bundle, target):
    path, _ = certificate(bundle)
    p = bundle[target]
    p.write_bytes(p.read_bytes() + b"\n")
    with pytest.raises((ValueError, HandoffError)):
        closeout.validate_minor_closeout(PID, str(path.relative_to(bundle["root"])), root=bundle["root"])


@pytest.mark.parametrize("field,value", [("confirmed", False), ("actor", "assistant"), ("minimum_score", 4),
                                        ("minimum_decision", "major_revision"), ("scope", "all_science"), ("papers", {})])
def test_authorization_cannot_broaden_or_weaken_gate(bundle, field, value):
    bundle["auth"][field] = value
    write(bundle["auth_path"], bundle["auth"])
    with pytest.raises(ValueError):
        prepare(bundle)


def revise_raw(b, change):
    raw = deepcopy(b["raw"])
    change(raw)
    write(b["raw_path"], raw)
    b["aggregator"].main(["--paper-id", PID, "--review-dir", str(b["review_dir"]), "--root", str(b["root"]), "--force"])
    b["auth"]["papers"][PID]["source_review_sha256"] = closeout._sha(b["raw_path"])
    write(b["auth_path"], b["auth"])


@pytest.mark.parametrize("case", ["science_false", "low_score", "cas_major", "hard_blocker", "nontext"])
def test_scientific_thresholds_and_unclassified_requests_cannot_be_waived(bundle, case):
    def change(raw):
        if case == "science_false": raw["publishability_summary"]["scientific_ready"] = False
        elif case == "low_score": raw["scores"]["overall"] = 4
        elif case == "cas_major": raw["recommendations"]["cas_zone_1_journal"]["decision"] = "major_revision"
        elif case == "hard_blocker": raw["unresolved_blockers"].append("Missing proof and contradictory evidence.")
        else: raw["change_requests"][0]["text_only"] = False
    revise_raw(bundle, change)
    with pytest.raises(ValueError): prepare(bundle)


def test_scientific_blocker_cannot_be_called_venue_only(bundle):
    bundle["auth"]["papers"][PID]["venue_suitability_blockers"] = ["Missing proof and ethics concern"]
    write(bundle["auth_path"], bundle["auth"])
    with pytest.raises(ValueError, match="venue-suitability"): prepare(bundle)


def test_precise_k5_venue_and_optional_classifications():
    raw = {"publishability_summary": {"text_ready": True}, "change_requests": [
        {"request": VENUE_REQUEST, "text_only": False, "priority": "high"},
        {"request": "Optionally explain the discovery.", "text_only": True, "priority": "low"}],
        "required_changes": [VENUE_REQUIRED]}
    auth = {"venue_suitability_change_requests": [VENUE_REQUEST], "venue_suitability_required_changes": [VENUE_REQUIRED],
            "optional_not_required_change_requests": ["Optionally explain the discovery."]}
    needed, required, excluded = closeout._request_plan(raw, auth)
    assert needed == required == []
    assert [x["classification"] for x in excluded] == ["venue_suitability_only", "optional_not_required"]
    raw["publishability_summary"]["text_ready"] = False
    with pytest.raises(ValueError, match="optional"): closeout._request_plan(raw, auth)
    raw["publishability_summary"]["text_ready"] = True
    raw["change_requests"][1]["priority"] = "high"
    with pytest.raises(ValueError, match="optional"): closeout._request_plan(raw, auth)


@pytest.mark.parametrize("name", ["science.py", "results/exact.txt", "proof.lean", "CLAIMS.yaml", "REPRODUCE.md", "data.csv"])
def test_scientific_support_changes_are_not_text_closeout(name):
    with pytest.raises(ValueError, match="scientific support"):
        closeout._deltas({name: b"claim: old\nversion: 0.1.0"}, {name: b"claim: stronger\nversion: 0.1.1"}, "support", "0.1.0", "0.1.1")


@pytest.mark.parametrize("name", ["CLAIMS.yaml", "REPRODUCE.md"])
def test_sensitive_support_allows_only_exact_version_substitution(name):
    rows = closeout._deltas({name: b"claim: unchanged\nversion: 0.1.0"},
                           {name: b"claim: unchanged\nversion: 0.1.1"}, "support", "0.1.0", "0.1.1")
    assert len(rows) == 1


def test_text_delta_is_explicit_and_file_deletion_is_forbidden():
    rows = closeout._deltas({"main.tex": b"old prose"}, {"main.tex": b"clear prose"}, "manuscript")
    assert rows[0]["path"] == "manuscript/main.tex"
    with pytest.raises(ValueError, match="added/deleted"):
        closeout._deltas({"main.tex": b"old"}, {}, "manuscript")


@pytest.mark.parametrize("target", ["certificate", "evidence", "score", "rounds"])
def test_handoff_revalidates_closeout_not_just_ready_label(bundle, target, monkeypatch):
    path, _ = certificate(bundle)
    closeout.apply_minor_closeout(PID, certificate=str(path.relative_to(bundle["root"])), root=bundle["root"])
    metadata = load_paper_metadata(PID, bundle["root"])
    if target == "certificate": path.write_bytes(path.read_bytes() + b"\n")
    elif target == "evidence": (bundle["root"] / "maintenance/closeout/evidence.md").write_text("changed evidence")
    elif target == "score": metadata["writing_release"]["score"] = 10
    else: metadata["writing_release"]["revision_rounds_completed"] = 1
    with pytest.raises(HandoffError, match="closeout"):
        _release_paths(PID, bundle["root"], metadata)
    write_paper_metadata(PID, metadata, bundle["root"])
    # Skip only unrelated remote-support lifecycle status; exercise the actual
    # release-precondition entry point, not merely its private file collector.
    monkeypatch.setattr("paper_writing.handoff.lifecycle_gate", lambda *a: {})
    with pytest.raises(HandoffError, match="closeout"):
        validate_release_preconditions(PID, root=bundle["root"])


@pytest.mark.parametrize("name", ["../outside", "/etc/passwd", "./file", "folder/../file", "a\\b"])
def test_unsafe_evidence_paths_are_rejected(tmp_path, name):
    with pytest.raises(ValueError): closeout._path(name, tmp_path)


def test_duplicate_json_keys_and_symlinks_are_rejected(tmp_path):
    path = tmp_path / "record.json"
    path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="duplicate"): closeout._json(path)
    (tmp_path / "alias.json").symlink_to(path)
    with pytest.raises(ValueError, match="symlinked"): closeout._path("alias.json", tmp_path)


def test_snapshot_only_notes_are_bound_without_claiming_packet_coverage():
    old = {"main.tex": b"old prose"}
    new = {"main.tex": b"clear prose"}
    complete_old = {**old, "README.md": b"private unchanged note"}
    full, extras = closeout._complete_sources(old, new,
        {**new, "README.md": complete_old["README.md"]}, b"original PDF",
        closeout._snapshot(complete_old, b"original PDF"))
    assert full == complete_old
    assert extras == [{"path": "README.md", "sha256": closeout.hashlib.sha256(complete_old["README.md"]).hexdigest(),
                       "in_review_packet": False}]


@pytest.mark.parametrize("case", ["changed", "added", "deleted", "not_markdown", "packet_members", "packet_bytes"])
def test_snapshot_only_compatibility_cannot_hide_source_changes(case):
    old, new = {"main.tex": b"old"}, {"main.tex": b"new"}
    complete_old = {**old, "README.md": b"unchanged"}
    current = {**new, "README.md": b"unchanged"}
    if case == "changed": current["README.md"] = b"edited"
    elif case == "added": current["extra.md"] = b"added"
    elif case == "deleted": del current["README.md"]
    elif case == "not_markdown": current["science.py"] = b"code"
    elif case == "packet_members": new["README.md"] = b"unchanged"
    else: new["main.tex"] = b"different"
    with pytest.raises(ValueError):
        closeout._complete_sources(old, new, current, b"PDF", closeout._snapshot(complete_old, b"PDF"))


def test_new_version_text_closeout_binds_new_snapshot_without_new_review(bundle):
    b = bundle
    metadata = load_paper_metadata(PID, b["root"])
    old_projection = deepcopy(metadata["ara_llm_self_review"])
    metadata["version"] = "0.1.1"
    main = b["manuscript"] / "main.tex"
    main.write_text(main.read_text() + "\n% Clarified notation; theorem unchanged.\n")
    b["pdf"].write_bytes(b"%PDF-1.4 rebuilt exact new fixture")
    source_dir = b["root"] / f"papers/{PID}/support-materials/public-support-v0.1.1"
    source_dir.mkdir()
    (source_dir / "science.py").write_text("# frozen science\n")
    (source_dir / "CLAIMS.yaml").write_text("version: 0.1.1\nclaim: unchanged\n")
    metadata["support"]["publication"]["source_files"] = [str(source_dir.relative_to(b["root"]))]
    support = build_support_archive(metadata, list(source_dir.iterdir()), repo_root=b["root"], origin_commit="a" * 40)
    b["support_path"] = support["archive"]
    metadata["support"]["publication"]["package_sha256"] = closeout._sha(b["support_path"])
    archive(b["source_path"], {p.relative_to(b["manuscript"]).as_posix(): p.read_bytes()
                             for p in _source_files(b["manuscript"], b["pdf"])})
    metadata["submission_package"].update(version="0.1.1", source_archive_sha256=closeout._sha(b["source_path"]))
    write_paper_metadata(PID, metadata, b["root"])
    b["auth"]["papers"][PID]["target_version"] = "0.1.1"
    write(b["auth_path"], b["auth"])
    path, cert = certificate(b)
    assert cert["target"]["manuscript_snapshot_sha256"] != old_projection["manuscript_snapshot_sha256"]
    assert any(d["path"] == "manuscript/main.tex" for d in cert["delta"])
    assert any(d["path"].endswith("/CLAIMS.yaml") for d in cert["delta"])
    closeout.apply_minor_closeout(PID, certificate=str(path.relative_to(b["root"])), root=b["root"])
    current = load_paper_metadata(PID, b["root"])
    assert current["ara_llm_self_review"] == old_projection
    assert current["writing_release"]["manuscript_version"] == "0.1.1"
    assert current["writing_release"]["revision_rounds_completed"] == 12
    assert path in _release_paths(PID, b["root"], current)[2]
