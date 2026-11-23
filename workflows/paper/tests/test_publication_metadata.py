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
