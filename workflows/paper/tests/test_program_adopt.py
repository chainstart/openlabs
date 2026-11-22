"""Adopting a campaign-workspace paper into the data repository; waiving the public deposit."""

import hashlib
import io
import json
import shutil
import tarfile

import pytest
import yaml

from paper_writing import formal_checks as formal
from paper_writing.handoff import manuscript_snapshot_sha256
from paper_writing.program_adopt import AdoptError, adopt, waive_support
from test_formal_checks import ROLE, run_fixture

PAPER = "20261119-quant-energy-example"
RUN = f"reviews/unified/{PAPER}/20261119T180614Z"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- formal check


def test_formal_check_revalidates_after_the_paper_moves_to_another_checkout(tmp_path, monkeypatch):
    review_root = tmp_path / "review-scratch"
    review_root.mkdir()
    metadata, binding, _ = run_fixture(review_root, monkeypatch)
    adopted = tmp_path / "data-repository"
    shutil.copytree(review_root, adopted)
    assert formal.validate_binding(binding, metadata, adopted, ROLE) == []


def test_relocated_formal_check_still_refuses_a_changed_manuscript(tmp_path, monkeypatch):
    review_root = tmp_path / "review-scratch"
    review_root.mkdir()
    metadata, binding, result = run_fixture(review_root, monkeypatch)
    adopted = tmp_path / "data-repository"
    shutil.copytree(review_root, adopted)
    # Only the evidence-root label may differ: an edited stored prompt is refused even when
    # its receipt hash is rebound to it.
    workdir = adopted / result["receipts"][0]["workdir"]
    prompt = (workdir / "prompt.txt").read_text().replace("x^2", "x^3")
    (workdir / "prompt.txt").write_text(prompt)
    assert formal.validate_binding(binding, metadata, adopted, ROLE)
    manuscript = adopted / metadata["manuscript_dir"] / "main.tex"
    manuscript.write_text(manuscript.read_text().replace("x^2", "x^3"))
    assert formal.validate_binding(binding, metadata, adopted, ROLE)


# --------------------------------------------------------------------------- adopt


def _workspace(root, *, availability="The analysis code is in the replication files."):
    manuscript = root / "papers" / PAPER / "manuscript"
    manuscript.mkdir(parents=True)
    (manuscript / "main.tex").write_text(
        "\\begin{document}\nBody \\cite{elliot}.\n\\section*{Data and code availability}\n"
        f"{availability}\n\\bibliography{{references}}\n\\end{{document}}\n")
    (manuscript / "references.bib").write_text(
        "@misc{elliot, doi = {10.5281/zenodo.23293832}, title = {Third-party code}}\n")
    (root / "analysis").mkdir()
    (root / "analysis" / "primary.py").write_text("print('analysis')\n")
    evidence = {"body": b"BODY BYTES", "text": b"TEXT BYTES"}
    report = {"sources": [{"body_path": f"{RUN}/formal-check/evidence/S1.body",
                           "body_sha256": _sha(evidence["body"]),
                           "text_path": f"{RUN}/formal-check/evidence/S1.text",
                           "text_sha256": _sha(evidence["text"])}]}
    run = root / RUN
    (run / "formal-check").mkdir(parents=True)
    (run / "formal-check" / "report.json").write_text(json.dumps(report))
    pdf_bytes = b"%PDF-1.4\nreviewed\n%%EOF\n"
    (manuscript / "main.pdf").write_bytes(pdf_bytes)
    snapshot = manuscript_snapshot_sha256(manuscript, manuscript / "main.pdf")
    (manuscript / "main.pdf").unlink()  # the attempt archive kept the PDF out of the workspace
    (run / "decision.json").write_text(json.dumps(
        {"fingerprints": {"manuscript_snapshot_sha256": snapshot}}))
    metadata = {
        "paper_id": PAPER, "version": "0.1.5",
        "manuscript_dir": f"papers/{PAPER}/manuscript",
        "writing_release": {"status": "ready", "decision_record": f"{RUN}/decision.json",
                            "formal_check": {"path": f"{RUN}/formal-check/report.json"}},
        "support": {"publication": {"mode": "zenodo_only", "status": "planned",
                                    "source_files": ["analysis/primary.py", "analysis/gone.py"]}},
    }
    (root / "registry" / "papers").mkdir(parents=True)
    (root / "registry" / "papers" / f"{PAPER}.yaml").write_text(yaml.safe_dump(metadata))
    return evidence, pdf_bytes


def _bundle(root, evidence, pdf_bytes):
    """An archived result bundle: a decoy PDF, the reviewed PDF and an evidence tarball."""

    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in (("formal-check/evidence/S1.body", evidence["body"]),
                           ("formal-check/evidence/S1.text", evidence["text"])):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    files = {"000-decoy.pdf": b"%PDF-1.4\nother build\n%%EOF\n", "001-main.pdf": pdf_bytes,
             "002-evidence.tar.gz": buffer.getvalue()}
    listed = []
    for name, data in files.items():
        (artifacts / name).write_bytes(data)
        listed.append({"artifact_id": name, "sha256": _sha(data),
                       "uri": (artifacts / name).resolve().as_uri()})
    (root / "manifest.json").write_text(json.dumps({"artifacts": listed}))
    (root / "result.json").write_text("{}")
    return root / "result.json"


@pytest.mark.parametrize("workspace_path", ["physics/campaign", "lines/photometry/campaign"])
def test_adopt_copies_the_paper_and_restores_hash_bound_files(tmp_path, workspace_path):
    data = tmp_path / "data"
    workspace = data / "workspaces" / workspace_path
    data.mkdir()
    evidence, pdf_bytes = _workspace(workspace)
    bundle = _bundle(tmp_path / "bundle", evidence, pdf_bytes)

    result = adopt(PAPER, root=data, source=workspace, artifact_manifests=[bundle])
    assert result["status"] == "adopted" and result["evidence_missing"] == []
    assert result["evidence_restored"] == 2
    assert result["pdf_restored"] == f"papers/{PAPER}/manuscript/main.pdf"
    assert (data / result["pdf_restored"]).read_bytes() == pdf_bytes
    assert (data / RUN / "formal-check/evidence/S1.body").read_bytes() == evidence["body"]
    assert (data / "registry/papers" / f"{PAPER}.yaml").read_bytes() == (
        workspace / "registry/papers" / f"{PAPER}.yaml").read_bytes()
    assert (data / "papers" / PAPER / "support-materials/analysis/primary.py").is_file()
    assert result["support_sources_missing"] == ["analysis/gone.py"]
    # Idempotent: a second run copies nothing and changes nothing.
    again = adopt(PAPER, root=data, source=workspace, artifact_manifests=[bundle])
    assert again["copied"] == 0 and again["evidence_restored"] == 0 and again["pdf_restored"] is None


def test_adopt_never_overwrites_different_files(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    _workspace(workspace)
    target = data / "papers" / PAPER / "manuscript" / "main.tex"
    target.parent.mkdir(parents=True)
    target.write_text("someone else's manuscript\n")
    with pytest.raises(AdoptError, match="different files"):
        adopt(PAPER, root=data, source=workspace)
    assert target.read_text() == "someone else's manuscript\n"
    assert not (data / "registry/papers" / f"{PAPER}.yaml").exists()


def test_adopt_restores_nothing_whose_hash_does_not_match(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    data.mkdir()
    evidence, _ = _workspace(workspace)
    bundle = _bundle(tmp_path / "bundle", {"body": b"forged", "text": evidence["text"]},
                     b"%PDF-1.4\nnot the reviewed build\n%%EOF\n")
    result = adopt(PAPER, root=data, source=workspace, artifact_manifests=[bundle])
    assert result["evidence_missing"] == [f"{RUN}/formal-check/evidence/S1.body"]
    assert result["pdf_restored"] is None
    assert not (data / "papers" / PAPER / "manuscript" / "main.pdf").exists()


# --------------------------------------------------------------------------- waive-support


def test_waive_support_records_not_required_with_its_reason(tmp_path):
    _workspace(tmp_path)
    result = waive_support(PAPER, root=tmp_path, reason="Owner 2026-11-20: no Zenodo records.",
                           decided_by="orchestrator:support_release=none")
    assert result["status"] == "waived"
    publication = yaml.safe_load((tmp_path / "registry/papers" / f"{PAPER}.yaml").read_text())[
        "support"]["publication"]
    assert publication["mode"] == "not_required"
    assert publication["not_required_reason"] == "Owner 2026-11-20: no Zenodo records."
    assert publication["not_required_recorded_by"] == "orchestrator:support_release=none"
    # The third-party Zenodo DOI in the bibliography is not a deposit of this paper.
    assert waive_support(PAPER, root=tmp_path, reason="x", decided_by="y")["status"] == "unchanged"


def test_waive_support_refuses_when_the_manuscript_names_a_deposit(tmp_path):
    _workspace(tmp_path, availability="Code: https://doi.org/10.5281/zenodo.1 (Zenodo).")
    result = waive_support(PAPER, root=tmp_path, reason="r", decided_by="d")
    assert result["status"] == "blocked" and result["reason"] == "manuscript_cites_deposit"
    publication = yaml.safe_load((tmp_path / "registry/papers" / f"{PAPER}.yaml").read_text())[
        "support"]["publication"]
    assert publication["mode"] == "zenodo_only"


def test_waive_support_refuses_an_existing_record(tmp_path):
    _workspace(tmp_path)
    path = tmp_path / "registry/papers" / f"{PAPER}.yaml"
    metadata = yaml.safe_load(path.read_text())
    metadata["support"]["publication"].update({"status": "draft",
                                               "version_doi": "10.5281/zenodo.9"})
    path.write_text(yaml.safe_dump(metadata))
    result = waive_support(PAPER, root=tmp_path, reason="r", decided_by="d")
    assert result["status"] == "blocked" and result["reason"] == "support_record_exists"


def test_adopt_refuses_an_unknown_layout_and_copies_nothing(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    data.mkdir()
    _workspace(workspace)
    path = workspace / "registry/papers" / f"{PAPER}.yaml"
    metadata = yaml.safe_load(path.read_text())
    metadata.update({"workspace": "drafts/paper", "manuscript_dir": "drafts/paper/manuscript"})
    path.write_text(yaml.safe_dump(metadata))
    result = adopt(PAPER, root=data, source=workspace)
    assert result["status"] == "blocked" and result["reason"] == "layout_unsupported"
    assert "only '.' can be relocated" in result["detail"]
    assert list(data.iterdir()) == []


def _root_layout_workspace(root):
    """A paper registered in a private review root: workspace '.', root-level manuscript/."""

    evidence, pdf_bytes = _workspace(root)
    canonical = root / "papers" / PAPER
    (canonical / "manuscript").rename(root / "manuscript")
    (root / "evidence").mkdir()
    (root / "evidence" / "runtime.json").write_text('{"model": "m"}\n')
    (canonical / "writing").mkdir(parents=True)
    (canonical / "writing" / "storyline.md").write_text("story\n")
    path = root / "registry/papers" / f"{PAPER}.yaml"
    metadata = yaml.safe_load(path.read_text())
    metadata.update({"workspace": ".", "manuscript_dir": "manuscript",
                     "latest_source": "manuscript/main.tex", "latest_pdf": "manuscript/main.pdf",
                     "subdomain": "manuscript",  # a bare word, not a *_dir field: untouched
                     "declarations": {"ai_use": {"model_usage": [
                         {"evidence": {"path": "evidence/runtime.json",
                                       "json_pointer": "/model"}}]}}})
    metadata["support"]["publication"]["source_files"] = ["analysis/primary.py"]
    path.write_text(yaml.safe_dump(metadata))
    return evidence, pdf_bytes


def test_adopt_carries_the_editorial_rewrite_record(tmp_path):
    """The unified-review preflight needs the target's rewrite record in the data repository."""
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    data.mkdir()
    _workspace(workspace)
    record = workspace / "reviews/editorial-rewrite" / PAPER / "20261119T092307Z" / "record.json"
    record.parent.mkdir(parents=True)
    record.write_text('{"outcome": "editorial_failed"}\n')
    result = adopt(PAPER, root=data, source=workspace)
    assert result["status"] == "adopted", result
    copied = data / record.relative_to(workspace)
    assert copied.read_bytes() == record.read_bytes()


def test_adopt_relocates_a_workspace_root_layout_byte_for_byte(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    data.mkdir()
    evidence, pdf_bytes = _root_layout_workspace(workspace)
    bundle = _bundle(tmp_path / "bundle", evidence, pdf_bytes)
    result = adopt(PAPER, root=data, source=workspace, artifact_manifests=[bundle])
    assert result["status"] == "adopted", result
    # Every top-level workspace entry the registry names moves; support sources included.
    assert result["relocated"]["segments"] == ["analysis", "evidence", "manuscript"]
    canonical = f"papers/{PAPER}"
    registry = yaml.safe_load((data / "registry/papers" / f"{PAPER}.yaml").read_text())
    assert registry["workspace"] == canonical
    assert registry["manuscript_dir"] == f"{canonical}/manuscript"
    assert registry["latest_pdf"] == f"{canonical}/manuscript/main.pdf"
    assert registry["declarations"]["ai_use"]["model_usage"][0]["evidence"] == {
        "path": f"{canonical}/evidence/runtime.json", "json_pointer": "/model"}
    assert registry["subdomain"] == "manuscript"
    assert registry["relocation"]["record"] == f"{canonical}/production/workspace-relocation.json"
    record = json.loads((data / registry["relocation"]["record"]).read_text())
    for item in record["files"]:
        assert _sha(workspace.joinpath(item["from"]).read_bytes()) == item["sha256"]
        assert _sha(data.joinpath(item["to"]).read_bytes()) == item["sha256"]
    assert {f["field"] for f in record["rewritten_fields"]} >= {
        "/manuscript_dir", "/workspace", "/declarations/ai_use/model_usage/0/evidence/path"}
    # The manuscript bytes are unchanged, so the reviewed snapshot is reproduced.
    assert result["pdf_restored"] == f"{canonical}/manuscript/main.pdf"
    assert (data / canonical / "writing/storyline.md").is_file()
    assert registry["support"]["publication"]["source_files"] == [f"{canonical}/analysis/primary.py"]
    assert (data / canonical / "analysis/primary.py").is_file()
    # Idempotent: the same relocation again changes nothing.
    again = adopt(PAPER, root=data, source=workspace, artifact_manifests=[bundle])
    assert again["status"] == "adopted" and again["copied"] == 0


def test_snapshot_restore_uses_an_archived_review_root(tmp_path):
    """Figures and build products only in an owner's archived review root are restored together."""

    workspace, data = tmp_path / "workspace", tmp_path / "data"
    data.mkdir()
    evidence, _ = _workspace(workspace)
    manuscript = workspace / "papers" / PAPER / "manuscript"
    figure, bbl, pdf = b"%PDF figure\n", b"\\begin{thebibliography}{0}\\end{thebibliography}\n", b"%PDF review build\n"
    (manuscript / "figures").mkdir()
    (manuscript / "figures/fit.pdf").write_bytes(figure)
    (manuscript / "main.bbl").write_bytes(bbl)
    (manuscript / "main.pdf").write_bytes(pdf)
    snapshot = manuscript_snapshot_sha256(manuscript, manuscript / "main.pdf")
    for name in ("figures/fit.pdf", "main.bbl", "main.pdf"):
        (manuscript / name).unlink()
    (workspace / RUN / "decision.json").write_text(json.dumps(
        {"fingerprints": {"manuscript_snapshot_sha256": snapshot}}))
    # Owner bundle: a private review root with the figure and .bbl but an older PDF.
    owner = tmp_path / "owner"
    (owner / "artifacts").mkdir(parents=True)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data_bytes in (("./manuscript/figures/fit.pdf", figure),
                                 ("./manuscript/main.bbl", bbl),
                                 ("./manuscript/main.pdf", b"%PDF older\n")):
            info = tarfile.TarInfo(name)
            info.size = len(data_bytes)
            archive.addfile(info, io.BytesIO(data_bytes))
    (owner / "artifacts/root.tar.gz").write_bytes(buffer.getvalue())
    (owner / "manifest.json").write_text(json.dumps({"artifacts": [
        {"artifact_id": "private-review-root", "sha256": _sha(buffer.getvalue()),
         "uri": (owner / "artifacts/root.tar.gz").resolve().as_uri()}]}))
    review = _bundle(tmp_path / "review", evidence, pdf)
    result = adopt(PAPER, root=data, source=workspace,
                   artifact_manifests=[review, owner / "manifest.json"])
    target = data / "papers" / PAPER / "manuscript"
    assert result["pdf_restored"] == f"papers/{PAPER}/manuscript/main.pdf"
    assert (target / "main.pdf").read_bytes() == pdf
    assert (target / "figures/fit.pdf").read_bytes() == figure
    assert manuscript_snapshot_sha256(target, target / "main.pdf") == snapshot


def test_registry_rejects_a_non_canonical_layout(tmp_path):
    from paper_writing.registry import paper_layout_problems

    assert paper_layout_problems(PAPER, {"workspace": f"papers/{PAPER}",
                                         "manuscript_dir": f"papers/{PAPER}/manuscript"}) == []
    problems = paper_layout_problems(PAPER, {"workspace": ".", "manuscript_dir": "manuscript"})
    assert len(problems) == 2


def _registry_root(root, record):
    (root / "registry/papers").mkdir(parents=True)
    (root / "registry/settings.yaml").write_text("schema_version: ara.paper_writing.registry.v1\n")
    (root / "registry/papers" / f"{PAPER}.yaml").write_text(yaml.safe_dump(record))


def test_an_existing_root_layout_record_still_loads_with_a_warning(tmp_path):
    """A paper under review in a private root keeps working; adopt relocates it later."""
    from paper_writing.operations import validate_repository
    from paper_writing.registry import load_registry

    (tmp_path / "manuscript").mkdir()
    (tmp_path / "manuscript/main.tex").write_text("\\begin{document}\\end{document}\n")
    _registry_root(tmp_path, {"paper_id": PAPER, "created_at": "2026-11-19", "domain": "quant",
                              "subdomain": "energy", "workspace": ".",
                              "manuscript_dir": "manuscript", "version": "0.1.0"})
    config = load_registry(tmp_path, include_local_repositories=False, paper_ids=[PAPER])
    assert "." in config["papers"]
    assert config["papers"]["."]["latest_source"] == "manuscript/main.tex"
    assert any("program adopt" in item for item in config["layout_warnings"])
    result = validate_repository(tmp_path)
    assert any(PAPER in item and "layout" in item for item in result["warnings"])


def test_a_new_record_must_use_the_canonical_layout_but_an_old_one_stays_editable(tmp_path):
    from paper_writing.registry import load_paper_metadata, write_paper_metadata

    (tmp_path / "registry/papers").mkdir(parents=True)
    with pytest.raises(ValueError, match="new registry record must use"):
        write_paper_metadata(PAPER, {"workspace": ".", "manuscript_dir": "manuscript"}, tmp_path)
    assert not (tmp_path / "registry/papers" / f"{PAPER}.yaml").exists()
    write_paper_metadata(PAPER, {"workspace": f"papers/{PAPER}",
                                 "manuscript_dir": f"papers/{PAPER}/manuscript"}, tmp_path)
    (tmp_path / "registry/papers" / f"{PAPER}.yaml").write_text(
        yaml.safe_dump({"paper_id": PAPER, "workspace": ".", "manuscript_dir": "manuscript"}))
    write_paper_metadata(PAPER, {"workspace": ".", "manuscript_dir": "manuscript",
                                 "version": "0.2.0"}, tmp_path)
    assert load_paper_metadata(PAPER, tmp_path)["version"] == "0.2.0"


def test_bind_release_artifacts_freezes_the_ignored_pdf(tmp_path, monkeypatch):
    import subprocess

    from paper_writing import handoff
    from paper_writing.program_adopt import bind_release_artifacts

    root = tmp_path / "openlabs-data"
    _workspace(root)
    manuscript = root / "papers" / PAPER / "manuscript"
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4\nreviewed\n%%EOF\n")
    (root / ".gitignore").write_text("**/*.pdf\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@t",
                    "commit", "-qm", "base"], check=True)
    files = [manuscript / "main.tex", manuscript / "references.bib", manuscript / "main.pdf"]
    monkeypatch.setattr(handoff, "_release_paths", lambda *a: (manuscript, files[-1], files))
    result = bind_release_artifacts(PAPER, root=root)
    assert result["status"] == "bound" and result["files"] == [f"papers/{PAPER}/manuscript/main.pdf"]
    manifest = root / result["manifest"]
    entry = json.loads(manifest.read_text())["files"][0]
    stored = tmp_path / "openlabs-artifacts" / "paper-support" / "sha256" / entry["sha256"] / "main.pdf"
    assert stored.read_bytes() == (manuscript / "main.pdf").read_bytes()
    package = yaml.safe_load((root / "registry/papers" / f"{PAPER}.yaml").read_text())[
        "submission_package"]
    assert package == {"artifact_manifest": {"path": result["manifest"],
                                             "sha256": _sha(manifest.read_bytes())}}
    assert bind_release_artifacts(PAPER, root=root)["status"] == "not_needed"


def test_bind_release_artifacts_rebinds_a_stale_manifest_after_a_new_build(tmp_path, monkeypatch):
    """A later version rebuilds main.pdf/main.bbl: the old manifest no longer covers them."""
    import subprocess

    from paper_writing import handoff
    from paper_writing.program_adopt import bind_release_artifacts
    from paper_writing.release_pipeline import unbound_release_artifacts
    from paper_writing.registry import load_paper_metadata

    root = tmp_path / "openlabs-data"
    _workspace(root)
    manuscript = root / "papers" / PAPER / "manuscript"
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4\nv0.1.5\n%%EOF\n")
    (root / ".gitignore").write_text("**/*.pdf\n**/*.bbl\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@t",
                    "commit", "-qm", "base"], check=True)
    files = [manuscript / "main.tex", manuscript / "references.bib", manuscript / "main.pdf"]
    monkeypatch.setattr(handoff, "_release_paths", lambda *a: (manuscript, files[2], files))
    first = bind_release_artifacts(PAPER, root=root)
    assert first["status"] == "bound"
    assert unbound_release_artifacts(PAPER, load_paper_metadata(PAPER, root), root) == []

    # The next version: a new PDF and a new .bbl that the old manifest never saw.
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4\nv0.1.6\n%%EOF\n")
    (manuscript / "main.bbl").write_text("\\begin{thebibliography}{1}\\end{thebibliography}\n")
    files.append(manuscript / "main.bbl")
    pdf, bbl = f"papers/{PAPER}/manuscript/main.pdf", f"papers/{PAPER}/manuscript/main.bbl"
    assert unbound_release_artifacts(PAPER, load_paper_metadata(PAPER, root), root) == [bbl, pdf]

    second = bind_release_artifacts(PAPER, root=root)
    assert second["status"] == "bound" and second["files"] == [bbl, pdf]
    manifest = root / second["manifest"]
    entries = {item["path"]: item["sha256"] for item in json.loads(manifest.read_text())["files"]}
    assert entries == {pdf: _sha((manuscript / "main.pdf").read_bytes()),
                       bbl: _sha((manuscript / "main.bbl").read_bytes())}
    package = load_paper_metadata(PAPER, root)["submission_package"]
    assert package["artifact_manifest"] == {"path": second["manifest"],
                                            "sha256": _sha(manifest.read_bytes())}
    assert bind_release_artifacts(PAPER, root=root)["status"] == "not_needed"

    # Only the PDF changes again: the rewrite still binds every current candidate.
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4\nv0.1.7\n%%EOF\n")
    assert unbound_release_artifacts(PAPER, load_paper_metadata(PAPER, root), root) == [pdf]
    third = bind_release_artifacts(PAPER, root=root)
    assert third["files"] == [bbl, pdf]


# --------------------------------------------------------------------------- unwaive, availability


def test_unwaive_support_restores_the_deposit_mode_and_keeps_the_history(tmp_path):
    from paper_writing.program_adopt import unwaive_support

    _workspace(tmp_path)
    (tmp_path / "registry/settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\nsupport_publication:\n  default_mode: zenodo_only\n")
    waive_support(PAPER, root=tmp_path, reason="pipeline waiver", decided_by="orchestrator:x")
    with pytest.raises(AdoptError, match="--reason and --by"):
        unwaive_support(PAPER, root=tmp_path, reason=" ", by="op")
    result = unwaive_support(PAPER, root=tmp_path, reason="user wants a public deposit",
                             by="coordinator")
    assert result == {"schema_version": "openlabs.support_unwaiver.v1", "paper_id": PAPER,
                      "status": "restored", "mode": "zenodo_only"}
    publication = yaml.safe_load((tmp_path / "registry/papers" / f"{PAPER}.yaml").read_text())[
        "support"]["publication"]
    assert publication["mode"] == "zenodo_only" and publication["status"] == "planned"
    assert "not_required_reason" not in publication
    history = publication["waiver_history"][-1]
    assert history["waived_reason"] == "pipeline waiver" and history["waived_by"] == "orchestrator:x"
    assert history["reverted_by"] == "coordinator" and history["restored_mode"] == "zenodo_only"
    assert unwaive_support(PAPER, root=tmp_path, reason="again", by="op")["status"] == "unchanged"


@pytest.mark.parametrize("statement,flagged", [
    ("The replication files include the input manifest and the analysis code.", True),
    ("Code and manifests are archived at \\url{https://doi.org/10.5281/zenodo.1}.", False),
    ("The supporting materials \\citep{support2026} contain the code.", False),
    ("The supplementary material contains the scripts.", False),
    ("All proofs are included in this article. No external dataset is required.", False),
])
def test_availability_statement_must_name_a_location(tmp_path, statement, flagged):
    from paper_writing.review_flow import availability_location_issues

    _workspace(tmp_path, availability=statement)
    metadata = yaml.safe_load((tmp_path / "registry/papers" / f"{PAPER}.yaml").read_text())
    issues = availability_location_issues(PAPER, metadata, tmp_path)
    assert bool(issues) is flagged
    if flagged:
        assert issues[0]["code"] == "DATA-AVAILABILITY-LOCATION"


def test_bind_oversize_payloads_moves_an_over_limit_evidence_body_out_of_git(tmp_path):
    """PMB-13B, 2026-11-20: an 8 MB formal-check evidence body refused by the blob limit.

    The file stays on disk byte for byte, is copied to the content-addressed store and
    recorded with its SHA-256, the .gitignore next to it keeps it out of Git, and the index
    entry the refused commit left staged is dropped; the next commit then passes a
    pre-commit hook that refuses blobs over 5 MiB.
    """
    import subprocess

    from paper_writing.program_adopt import bind_oversize_payloads
    from paper_writing.release_pipeline import commit_paths, oversize_payloads
    from paper_writing.registry import load_paper_metadata
    from paper_writing.support import GIT_PAYLOAD_LIMIT_BYTES

    root = tmp_path / "openlabs-data"
    _workspace(root)
    git = ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "base"], check=True)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\ngit diff --cached --name-only -z --diff-filter=AM | "
                    f"xargs -0 -r -I{{}} sh -c 'test $(wc -c < \"{{}}\") -le "
                    f"{GIT_PAYLOAD_LIMIT_BYTES} || {{ echo refusing {{}}; exit 1; }}'\n")
    hook.chmod(0o755)

    evidence = root / RUN / "formal-check" / "evidence"
    evidence.mkdir(parents=True)
    big = evidence / "S71c226eba714f63bcbed.body"
    payload = b"%PDF-1.7\n" + b"x" * (GIT_PAYLOAD_LIMIT_BYTES + 1024)
    big.write_bytes(payload)
    (evidence / "S71c226eba714f63bcbed.text").write_text("extracted text\n")
    big_name = big.relative_to(root).as_posix()
    # The refused commit attempt left everything staged.
    subprocess.run([*git, "add", "-A", "--", "reviews"], check=True)
    refused = subprocess.run([*git, "commit", "-qm", "release", "--", "reviews"],
                             capture_output=True, text=True)
    assert refused.returncode != 0

    metadata = load_paper_metadata(PAPER, root)
    paths = commit_paths(PAPER, metadata, root)
    assert oversize_payloads(PAPER, paths, root) == [big_name]

    result = bind_oversize_payloads(PAPER, root=root)
    assert result["status"] == "bound" and result["unstaged"] == [big_name]
    entry = result["files"][0]
    assert entry["path"] == big_name and entry["sha256"] == _sha(payload)
    assert entry["size"] == len(payload)
    stored = (tmp_path / "openlabs-artifacts" / "paper-support" / "sha256" / _sha(payload)
              / big.name)
    assert stored.read_bytes() == payload and big.read_bytes() == payload
    manifest = json.loads((root / result["manifest"]).read_text())
    assert manifest["files"][0]["artifact_uri"] == stored.resolve().as_uri()
    assert result["gitignore"] == [f"{RUN}/formal-check/evidence/.gitignore"]
    assert oversize_payloads(PAPER, paths, root) == []
    assert bind_oversize_payloads(PAPER, root=root)["status"] == "not_needed"

    present = [item for item in paths if (root / item).exists()]
    subprocess.run([*git, "add", "-A", "--", *present], check=True)
    subprocess.run([*git, "commit", "-qm", "release", "--", *present], check=True)
    tracked = subprocess.run([*git, "ls-files"], capture_output=True, text=True).stdout
    assert big_name not in tracked
    assert f"{RUN}/formal-check/evidence/S71c226eba714f63bcbed.text" in tracked
    assert f"papers/{PAPER}/production/payload-artifacts.json" in tracked

    # Changed bytes after binding: listed again and rebound to the new content.
    changed = payload + b"more"
    big.write_bytes(changed)
    assert oversize_payloads(PAPER, paths, root) == [big_name]
    again = bind_oversize_payloads(PAPER, root=root)
    assert again["files"][0]["sha256"] == _sha(changed)
    assert oversize_payloads(PAPER, paths, root) == []


def test_config_default_follows_root_not_the_workspace_environment(tmp_path, monkeypatch):
    """2026-11-20: the tick's OPENLABS_WORKSPACE made `zenodo prepare --root <data>` read
    <workspace>/data/registry/settings.yaml, a directory that does not exist."""
    from paper_writing import __main__ as cli

    monkeypatch.setenv("OPENLABS_WORKSPACE", str(tmp_path / "elsewhere"))
    seen = {}

    def fake_plan(record, files, *, environment, repo_root):
        seen["root"] = repo_root
        return {"ready": True}

    def fake_find(paper_id, *, repo_root, config_path):
        seen["config"] = config_path
        return {"support": {}}

    monkeypatch.setattr("paper_writing.zenodo.find_paper_record", fake_find)
    monkeypatch.setattr("paper_writing.zenodo.build_deposit_plan", fake_plan)
    root = tmp_path / "openlabs-data"
    code = cli.main(["zenodo", "plan", "--paper-id", PAPER, "--root", str(root)])
    assert code == 0
    assert seen["config"] == str(root / "registry" / "settings.yaml")


def test_relocated_support_sources_keep_the_reviewed_support_digest(tmp_path):
    """PMB-13B: support sources registered relative to the campaign workspace."""
    from paper_writing.program_adopt import relocate_support_sources, unadopted_support_sources
    from paper_writing.registry import load_paper_metadata, write_paper_metadata
    from paper_writing.support import support_sources_snapshot_sha256

    sources = [f"papers/{PAPER}/evidence/map.md", "decisive/solve.py", "precheck/farms.csv"]
    contents = {sources[0]: b"# map\n", sources[1]: b"print(1)\n", sources[2]: b"a,b\n1,2\n"}
    workspace, root = tmp_path / "workspace", tmp_path / "openlabs-data"
    record = {"paper_id": PAPER, "workspace": f"papers/{PAPER}",
              "manuscript_dir": f"papers/{PAPER}/manuscript", "version": "0.1.0",
              "support": {"publication": {"mode": "zenodo_only", "source_files": sources}}}
    for base in (workspace, root):
        (base / "registry/papers").mkdir(parents=True)
        write_paper_metadata(PAPER, record, base)
    for name, data in contents.items():
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copy = root / (name if name.startswith("papers/")
                       else f"papers/{PAPER}/support-materials/{name}")
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data)
    reviewed = support_sources_snapshot_sha256(load_paper_metadata(PAPER, workspace),
                                               repo_root=workspace)
    metadata = load_paper_metadata(PAPER, root)
    metadata["writing_release"] = {"support_sources_sha256": reviewed}
    write_paper_metadata(PAPER, metadata, root)
    assert [item[0] for item in unadopted_support_sources(PAPER, metadata, root)] == sources[1:]

    result = relocate_support_sources(PAPER, root=root)
    assert result["status"] == "relocated" and result["matches_review"] is True
    after = load_paper_metadata(PAPER, root)
    publication = after["support"]["publication"]
    assert publication["source_files"] == [
        sources[0], f"papers/{PAPER}/support-materials/decisive/solve.py",
        f"papers/{PAPER}/support-materials/precheck/farms.csv"]
    assert publication["adopted_sources"][
        f"papers/{PAPER}/support-materials/decisive/solve.py"] == "decisive/solve.py"
    from paper_writing.support import support_sources_logical_paths, support_sources_digest
    assert support_sources_digest(support_sources_logical_paths(after, repo_root=root)) == reviewed
    assert support_sources_snapshot_sha256(after, repo_root=root) == reviewed
    assert relocate_support_sources(PAPER, root=root)["status"] == "not_needed"
    # Changed bytes are not hidden by the alias: the digest moves.
    (root / f"papers/{PAPER}/support-materials/decisive/solve.py").write_bytes(b"print(2)\n")
    assert support_sources_snapshot_sha256(after, repo_root=root) != reviewed


def test_support_prepare_discovers_adopted_sources_without_previous_deposits(tmp_path):
    from paper_writing.support import resolve_support_sources

    directory = tmp_path / "papers" / PAPER / "support-materials"
    archive = directory / "zenodo" / "old.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"old")
    source = directory / "analysis.py"
    source.write_text("x = 1")
    record = {"paper_id": PAPER, "support": {"publication": {"status": "planned"}}}
    assert resolve_support_sources(record, repo_root=tmp_path, discover=True) == [source]


def test_adopt_registers_analysis_sources_when_owner_omits_list(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
    _workspace(workspace)
    path = workspace / "registry/papers" / f"{PAPER}.yaml"
    metadata = yaml.safe_load(path.read_text())
    del metadata["support"]["publication"]["source_files"]
    path.write_text(yaml.safe_dump(metadata))
    assert adopt(PAPER, source=workspace, root=data)["status"] == "adopted"
    registered = yaml.safe_load((data / path.relative_to(workspace)).read_text())
    assert registered["support"]["publication"]["source_files"] == ["analysis/primary.py"]
    assert (data / "papers" / PAPER / "support-materials/analysis/primary.py").is_file()


def test_adopt_revision_requires_matching_delivery_and_new_bound_decision(tmp_path, monkeypatch):
    from paper_writing import review_flow
    from paper_writing.program_adopt import adopt_revision

    workspace, data = tmp_path / "workspace", tmp_path / "data"
    evidence, pdf = _workspace(workspace)
    bundle = _bundle(tmp_path / "bundle", evidence, pdf)
    record = workspace / "registry/papers" / f"{PAPER}.yaml"
    candidate = yaml.safe_load(record.read_text())
    candidate["delivery"] = {"version": "0.1.4", "package_id": "pkg_old"}
    candidate["writing_release"]["manuscript_version"] = "0.1.5"
    record.write_text(yaml.safe_dump(candidate))
    target = data / record.relative_to(workspace)
    target.parent.mkdir(parents=True)
    target.write_text(yaml.safe_dump({**candidate, "version": "0.1.4"}))
    with pytest.raises(AdoptError, match="expected delivery"):
        adopt_revision(PAPER, root=data, source=workspace, previous_package="wrong")
    args = dict(root=data, source=workspace, previous_package="pkg_old", artifact_manifests=[bundle])
    with pytest.raises(AdoptError, match="review is not current"):
        adopt_revision(PAPER, **args)
    assert yaml.safe_load(target.read_text())["version"] == "0.1.4"
    monkeypatch.setattr(review_flow, "validate_unified_release", lambda *args: [])
    assert adopt_revision(PAPER, **args)["status"] == "adopted"
    assert yaml.safe_load(target.read_text())["version"] == "0.1.5"
    assert adopt_revision(PAPER, **args)["copied"] == 0
