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
