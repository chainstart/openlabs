import shutil

import pytest

from paper_writing import publication_metadata as pm
from paper_writing.handoff import manuscript_snapshot_sha256


def test_publication_projection_recovers_reviewed_snapshot_and_refuses_science_edits(tmp_path):
    paper = tmp_path / "papers" / "p"
    manuscript = paper / "manuscript"
    manuscript.mkdir(parents=True)
    tex = manuscript / "main.tex"
    tex.write_text(r"\section{Results}" + "\nThe result is 42.\n\n"
                   r"\section*{Data availability}" + "\nThe inputs are archived.\n")
    (manuscript / "references.bib").write_text("@article{example, title={Study}}\n")
    old_pdf = manuscript / "p-v1.0.0.pdf"
    old_pdf.write_bytes(b"reviewed pdf")
    expected = manuscript_snapshot_sha256(manuscript, old_pdf)
    publication = {"zenodo": {"reserved_version_doi": "10.5281/zenodo.123",
                              "version": "1.0.1", "creators": [{"name": "A Researcher"}],
                              "title": "Supporting material", "publication_date": "2026-11-22"}}
    metadata = {"paper_id": "p", "version": "1.0.1", "support": {"publication": publication},
                "manuscript_dir": "papers/p/manuscript", "latest_pdf": "papers/p/manuscript/main.pdf"}
    release = {"decision_record_sha256": "a" * 64, "publication_metadata": {
        "identity": list(pm._identity(publication)), "original_pdf": old_pdf.name,
        "had_bbl": False, "version": "1.0.1",
    }}
    history = pm._history(tmp_path, metadata, release["decision_record_sha256"])
    (history / "sources").mkdir(parents=True)
    for path, content in pm._edits(manuscript, publication).items():
        shutil.copyfile(path, history / "sources" / path.name)
        path.write_bytes(content)
    old_pdf.rename(history / old_pdf.name)
    (manuscript / "main.pdf").write_bytes(b"rebuilt pdf")
    (manuscript / "main.bbl").write_bytes(b"rebuilt bibliography")
    assert pm.KEY in tex.read_text()
    assert pm.baseline_fingerprints(tmp_path, metadata, release)["manuscript_snapshot_sha256"] == expected
    tex.write_text(tex.read_text().replace("42", "41"))
    with pytest.raises(ValueError, match="deterministic edit"):
        pm.baseline_fingerprints(tmp_path, metadata, release)


def test_paper_paths_default_when_registry_omits_manuscript_dir_and_latest_pdf(tmp_path):
    # 2026-11-24: a registry without latest_pdf (release-status defaults it to main.pdf)
    # made prepare-publication-metadata fail with KeyError 'latest_pdf'.
    (tmp_path / "papers" / "p" / "manuscript").mkdir(parents=True)
    paper, manuscript, pdf = pm._paper_paths(tmp_path, {"paper_id": "p"})
    assert paper == tmp_path / "papers" / "p"
    assert manuscript == paper / "manuscript"
    assert pdf == manuscript / "main.pdf"
    explicit = pm._paper_paths(tmp_path, {"paper_id": "p", "manuscript_dir": "papers/p/manuscript",
                                          "latest_pdf": "papers/p/manuscript/p-v1.0.0.pdf"})
    assert explicit[2] == manuscript / "p-v1.0.0.pdf"


def test_registered_support_key_is_rewritten_in_place_and_reversible(tmp_path):
    # 2026-11-24: a manuscript that already cites the previous support version under the
    # registered bibliography_key got a second openlabsSupportArchive entry, which the
    # formal check then looked up as an external DOI (unpublished draft: 404).
    paper = tmp_path / "papers" / "p"
    manuscript = paper / "manuscript"
    manuscript.mkdir(parents=True)
    tex = manuscript / "main.tex"
    tex.write_text(r"\section{Results}" + "\nThe result is 42.\n\n"
                   r"\section*{Data availability}" + "\nCode is on Zenodo \\citep{solarSupport}.\n")
    bib = manuscript / "references.bib"
    old_entry = ("@misc{solarSupport,\n  author = {A Researcher},\n  title = {Supporting material},\n"
                 "  year = {2026},\n  publisher = {Zenodo},\n  version = {1.0.0},\n"
                 "  doi = {10.5281/zenodo.111},\n  url = {https://doi.org/10.5281/zenodo.111}\n}\n")
    bib.write_text("@article{example, title={Study}}\n\n" + old_entry)
    pdf = manuscript / "main.pdf"
    pdf.write_bytes(b"reviewed pdf")
    expected = manuscript_snapshot_sha256(manuscript, pdf)
    publication = {"bibliography_key": "solarSupport",
                   "zenodo": {"reserved_version_doi": "10.5281/zenodo.222",
                              "version": "1.0.1", "creators": [{"name": "A Researcher"}],
                              "title": "Supporting material", "publication_date": "2026-11-22"}}
    assert pm.citation_key(manuscript, publication) == "solarSupport"
    edits = pm._edits(manuscript, publication)
    assert set(edits) == {bib}  # no new sentence in main.tex
    new = edits[bib].decode()
    assert "openlabsSupportArchive" not in new
    assert "version = {1.0.1}" in new and "doi = {10.5281/zenodo.222}" in new
    assert "url = {https://doi.org/10.5281/zenodo.222}" in new and "zenodo.111" not in new
    assert new.startswith("@article{example, title={Study}}")

    metadata = {"paper_id": "p", "version": "1.0.1", "support": {"publication": publication}}
    release = {"decision_record_sha256": "b" * 64, "publication_metadata": {
        "identity": list(pm._identity(publication)), "original_pdf": "main.pdf",
        "had_bbl": False, "version": "1.0.1",
    }}
    history = pm._history(tmp_path, metadata, release["decision_record_sha256"])
    (history / "sources").mkdir(parents=True)
    shutil.copyfile(bib, history / "sources" / "references.bib")
    bib.write_bytes(edits[bib])
    pdf.rename(history / "main.pdf")
    pdf.write_bytes(b"rebuilt pdf")
    assert pm.baseline_fingerprints(tmp_path, metadata, release)["manuscript_snapshot_sha256"] == expected

    # Without a registered key (or with a key absent from the bibliography) the
    # original append behaviour is kept.
    assert pm.citation_key(manuscript, {"bibliography_key": "missingKey"}) == pm.KEY
    assert pm.citation_key(manuscript, {}) == pm.KEY


def test_build_log_with_non_utf8_bytes_is_decoded(tmp_path, monkeypatch):
    # 2026-11-24: bibtex wrote a Latin-1 byte (0xfc) into latexmk's output and the
    # projection failed with UnicodeDecodeError instead of building (TIC 421871796).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "latexmk"
    fake.write_bytes(b"#!/bin/sh\nprintf 'M\\374ller et al.\\n'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(pm.shutil, "which", lambda name: str(fake))
    result = pm._build_pdf(tmp_path)
    assert result.returncode == 0
    assert result.stdout.startswith("M") and "ller et al." in result.stdout
