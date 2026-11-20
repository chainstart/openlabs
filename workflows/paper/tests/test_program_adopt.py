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


def test_adopt_copies_the_paper_and_restores_hash_bound_files(tmp_path):
    workspace, data = tmp_path / "workspace", tmp_path / "data"
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
