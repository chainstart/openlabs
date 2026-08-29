import hashlib
import json
import zipfile
from pathlib import Path

import yaml

from paper_writing.operations import record_quality_gate
from paper_writing.registry import load_paper_metadata
from paper_writing.support import build_support_archive
from paper_writing.support_citations import (
    _archive_filename_is_registered,
    audit_manuscript_support,
)


PAPER_ID = "20260806-math-graph-support-citation-audit"


def _write_settings(root: Path) -> None:
    (root / "registry" / "papers").mkdir(parents=True)
    (root / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
require_registration: true
quality_gate:
  minimum_score: 6.0
  require_validated_independent_review: false
  maximum_revision_rounds: 3
  decision_standard: cas_zone_1_journal
  cas_zone_1_minimum_decision: minor_revision
defaults: {}
""",
        encoding="utf-8",
    )


def _workspace(
    root: Path,
    *,
    process_prose: bool = False,
    stale_title: bool = False,
    stale_record_title: bool = False,
    archived_version: str = "1.0.0",
    archive_process_prose: bool = False,
    archive_evaluation_projection: bool = False,
    nested_identity_stale: bool = False,
    nested_checksum_overclaim: bool = False,
    nested_checksum_qualified_claim: bool = False,
) -> None:
    _write_settings(root)
    manuscript = root / "papers" / PAPER_ID / "manuscript"
    evidence = root / "papers" / PAPER_ID / "evidence"
    package_dir = root / "papers" / PAPER_ID / "support-materials" / "zenodo" / "v1.0.0"
    manuscript.mkdir(parents=True)
    evidence.mkdir(parents=True)
    package_dir.mkdir(parents=True)
    public_source = evidence / f"public-support-v{archived_version}"
    public_source.mkdir()
    source = public_source / "certificate.json"
    source.write_text(
        '{"qa_status": "PASS_INTERNAL"}\n'
        if archive_evaluation_projection
        else '{"verified": true}\n',
        encoding="utf-8",
    )
    doi = "10.5281/zenodo.12345678"
    title = (
        "A Prior Paper Title: supporting materials"
        if stale_record_title
        else "A Support Citation Audit: supporting materials"
    )
    claim_map = evidence / "claim_evidence_map.md"
    archive_narrative = (
        "During prepublication review this DOI is reserved; after authorized release it becomes public."
        if archive_process_prose
        else "The record provides the exact certificate and replay instructions."
    )
    claim_map.write_text(
        "# Claim--evidence map\n\n"
        f"Supporting materials: Zenodo version {archived_version}, Version DOI `{doi}`. "
        f"{archive_narrative}\n",
        encoding="utf-8",
    )
    release_sources = [claim_map, source]
    if nested_identity_stale:
        nested = public_source / "calculation-support-v0.9.0.zip"
        with zipfile.ZipFile(nested, "w") as payload:
            payload.writestr(
                "CITATION.cff",
                """cff-version: 1.2.0
message: "Cite this Zenodo supporting-material version."
type: dataset
title: "A Prior Paper Title: Supporting Materials"
version: 0.9.0
doi: 10.5281/zenodo.11111111
authors:
  - family-names: Lovelace
    given-names: Ada
""",
            )
            payload.writestr(
                "README.md",
                "# A Prior Paper Title: Supporting Materials\n\n"
                "Version 0.9.0, DOI 10.5281/zenodo.11111111.\n",
            )
            payload.writestr(
                "ZENODO_MANIFEST.json",
                json.dumps(
                    {
                        "paper_id": PAPER_ID,
                        "release_version": "0.9.0",
                        "version_doi": "10.5281/zenodo.11111111",
                        "title": "A Prior Paper Title",
                    }
                ),
            )
        release_sources.append(nested)
    if nested_checksum_overclaim:
        nested = public_source / "calculation-support-v1.0.0.zip"
        payload_bytes = b"verified payload\n"
        with zipfile.ZipFile(nested, "w") as payload:
            payload.writestr(
                "CITATION.cff",
                """cff-version: 1.2.0
message: "Cite this Zenodo supporting-material version."
type: dataset
title: "A Support Citation Audit: Supporting Materials"
version: 1.0.0
doi: 10.5281/zenodo.12345678
authors:
  - family-names: Lovelace
    given-names: Ada
""",
            )
            payload.writestr(
                "README.md",
                "# A Support Citation Audit: Supporting Materials\n\n"
                "Version 1.0.0, DOI 10.5281/zenodo.12345678.\n"
                "SHA256SUMS authenticates every archive member, and "
                "ZENODO_MANIFEST.json records the same paths.\n",
            )
            payload.writestr("payload.txt", payload_bytes)
            manifest_bytes = json.dumps(
                {
                    "paper_id": PAPER_ID,
                    "release_version": "1.0.0",
                    "version_doi": "10.5281/zenodo.12345678",
                    "title": "A Support Citation Audit",
                    "files": [
                        {
                            "path": "payload.txt",
                            "bytes": len(payload_bytes),
                            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                        }
                    ],
                }
            ).encode("utf-8")
            payload.writestr("ZENODO_MANIFEST.json", manifest_bytes)
            payload.writestr(
                "SHA256SUMS",
                f"{hashlib.sha256(payload_bytes).hexdigest()}  payload.txt\n"
                f"{hashlib.sha256(manifest_bytes).hexdigest()}  ZENODO_MANIFEST.json\n",
            )
        release_sources.append(nested)
    if nested_checksum_qualified_claim:
        nested = public_source / "calculation-support-v1.0.0.zip"
        citation_bytes = b"""cff-version: 1.2.0
message: "Cite this Zenodo supporting-material version."
type: dataset
title: "A Support Citation Audit: Supporting Materials"
version: 1.0.0
doi: 10.5281/zenodo.12345678
authors:
  - family-names: Lovelace
    given-names: Ada
"""
        readme_bytes = (
            "# A Support Citation Audit: Supporting Materials\n\n"
            "Version 1.0.0, DOI 10.5281/zenodo.12345678.\n"
            "SHA256SUMS authenticates every archive member except itself.\n"
            "ZENODO_MANIFEST.json records the 3 non-integrity payload members; "
            "it omits itself and SHA256SUMS.\n"
        ).encode("utf-8")
        payload_bytes = b"verified payload\n"
        payload_members = {
            "CITATION.cff": citation_bytes,
            "README.md": readme_bytes,
            "payload.txt": payload_bytes,
        }
        manifest_bytes = json.dumps(
            {
                "paper_id": PAPER_ID,
                "release_version": "1.0.0",
                "version_doi": "10.5281/zenodo.12345678",
                "title": "A Support Citation Audit",
                "files": [
                    {
                        "path": name,
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                    for name, content in payload_members.items()
                ],
            },
            sort_keys=True,
        ).encode("utf-8")
        checksummed_members = {
            **payload_members,
            "ZENODO_MANIFEST.json": manifest_bytes,
        }
        with zipfile.ZipFile(nested, "w") as payload:
            for name, content in checksummed_members.items():
                payload.writestr(name, content)
            payload.writestr(
                "SHA256SUMS",
                "".join(
                    f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                    for name, content in checksummed_members.items()
                ),
            )
        release_sources.append(nested)
    prose = (
        "During prepublication review this DOI is reserved; after authorized release "
        "it becomes public."
        if process_prose
        else "The archive contains the exact certificate and replay instructions."
    )
    (manuscript / "main.tex").write_text(
        """\\documentclass{article}
\\begin{document}
The supporting materials \\citep{supportRecord} are identified by the cited
Version DOI. """
        + prose
        + """

\\section*{Data and code availability}
The supporting-material record \\citep{supportRecord} contains the exact certificate.
\\bibliography{references}
\\end{document}
""",
        encoding="utf-8",
    )
    (manuscript / "references.bib").write_text(
        """@misc{supportRecord,
  author = {Ada Lovelace},
  title = {"""
        + ("A Stale Title" if stale_title else title)
        + """},
  publisher = {Zenodo},
  version = {1.0.0},
  doi = {10.5281/zenodo.12345678},
  url = {https://doi.org/10.5281/zenodo.12345678},
  note = {Supporting materials, CC BY 4.0}
}
""",
        encoding="utf-8",
    )
    record = {
        "paper_id": PAPER_ID,
        "workspace": f"papers/{PAPER_ID}",
        "created_at": "2026-08-06",
        "domain": "math",
        "subdomain": "graph",
        "title": "A Support Citation Audit",
        "authors": [{"name": "Ada Lovelace"}],
        "version": "1.0.0",
        "venue_type": "journal",
        "manuscript_dir": f"papers/{PAPER_ID}/manuscript",
        "latest_source": f"papers/{PAPER_ID}/manuscript/main.tex",
        "latest_pdf": f"papers/{PAPER_ID}/manuscript/main.pdf",
        "evidence_bundles": [],
        "support": {
            "publication": {
                "mode": "zenodo_only",
                "status": "draft",
                "license": "cc-by-4.0",
                "source_files": [str(path.relative_to(root)) for path in release_sources],
                "zenodo": {
                    "environment": "production",
                    "deposition_id": 12345678,
                    "reserved_version_doi": doi,
                    "version": "1.0.0",
                    "title": title,
                    "creators": [{"name": "Lovelace, Ada"}],
                    "license": "cc-by-4.0",
                },
            }
        },
    }
    archive = build_support_archive(
        record,
        release_sources,
        repo_root=root,
        output=package_dir / f"{PAPER_ID}-support-v1.0.0.zip",
        reserved_doi=doi,
        origin_commit="a" * 40,
        license_id="cc-by-4.0",
    )
    publication = record["support"]["publication"]
    publication["package_files"] = [
        str(Path(archive["archive"]).relative_to(root)),
        str(Path(archive["checksum"]).relative_to(root)),
    ]
    publication["package_size"] = archive["archive_size"]
    publication["package_sha256"] = archive["archive_sha256"]
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4\n% test\n")
    (root / "registry" / "papers" / f"{PAPER_ID}.yaml").write_text(
        yaml.safe_dump(record, sort_keys=False), encoding="utf-8"
    )


def test_support_audit_accepts_current_neutral_citation(tmp_path: Path) -> None:
    _workspace(tmp_path)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is True
    assert result["bibliography_key"] == "supportRecord"
    assert result["current_version_doi"] == "10.5281/zenodo.12345678"


def test_nested_support_zip_filename_is_valid_only_when_shipped() -> None:
    members = (
        "support-materials/public-support-v1.0.0/computation-support-v0.9.0.zip",
    )

    assert _archive_filename_is_registered(
        "paper-support-v1.0.0.zip",
        outer_archive_name="paper-support-v1.0.0.zip",
        outer_members=members,
    )
    assert _archive_filename_is_registered(
        "computation-support-v0.9.0.zip",
        outer_archive_name="paper-support-v1.0.0.zip",
        outer_members=members,
    )
    assert not _archive_filename_is_registered(
        "missing-support-v0.8.0.zip",
        outer_archive_name="paper-support-v1.0.0.zip",
        outer_members=members,
    )


def test_published_record_may_keep_sidecar_as_local_verification_file(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    publication = record["support"]["publication"]
    publication["status"] = "published"
    publication["version_doi"] = "10.5281/zenodo.12345678"
    publication["zenodo"]["version_doi"] = "10.5281/zenodo.12345678"
    publication["package_files"], publication["verification_files"] = (
        [publication["package_files"][0]],
        [publication["package_files"][1]],
    )
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is True


def test_support_audit_rejects_process_history_and_stale_title(tmp_path: Path) -> None:
    _workspace(tmp_path, process_prose=True, stale_title=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-PROCESS-NARRATIVE" in codes
    assert "SUPPORT-DRAFT-PUBLIC-CLAIM" in codes
    assert "SUPPORT-BIB-TITLE" in codes


def test_support_audit_rejects_process_history_in_standalone_reproducibility_statement(
    tmp_path: Path,
) -> None:
    _workspace(tmp_path)
    statement = (
        tmp_path
        / "papers"
        / PAPER_ID
        / "manuscript"
        / "reproducibility_statement.md"
    )
    statement.write_text(
        "# Reproducibility statement\n\n"
        "The Zenodo draft receipt verifies the supporting-material archive.\n",
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is False
    assert any(
        item["code"] == "SUPPORT-PROCESS-NARRATIVE"
        and item.get("path", "").endswith("reproducibility_statement.md")
        for item in result["errors"]
    )


def test_support_audit_rejects_stale_standalone_title_and_claim_id(
    tmp_path: Path,
) -> None:
    _workspace(tmp_path)
    workspace = tmp_path / "papers" / PAPER_ID
    (workspace / "evidence" / "claim_evidence_map.md").write_text(
        "# Claim--evidence map\n\n"
        "| Claim ID | Claim |\n"
        "|---|---|\n"
        "| `AUDIT-C1` | Current claim |\n",
        encoding="utf-8",
    )
    (workspace / "manuscript" / "reproducibility_statement.md").write_text(
        "# Reproducibility Statement for A Prior Paper Title\n\n"
        "The Zenodo record contains the exact certificate.\n"
        "Claim routing: the map uses `AUDIT-C1` and `LEGACY-C9`.\n",
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-STATEMENT-PAPER-TITLE" in codes
    assert "SUPPORT-STATEMENT-CLAIM-ID" in codes


def test_support_audit_rejects_record_title_for_prior_paper_title(tmp_path: Path) -> None:
    _workspace(tmp_path, stale_record_title=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-RECORD-PAPER-TITLE" in codes


def test_support_audit_rejects_stale_identity_in_nested_current_payload(tmp_path: Path) -> None:
    _workspace(tmp_path, nested_identity_stale=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-ARCHIVE-IDENTITY-VERSION" in codes
    assert "SUPPORT-ARCHIVE-IDENTITY-DOI" in codes
    assert "SUPPORT-ARCHIVE-IDENTITY-TITLE" in codes


def test_support_audit_rejects_overstated_nested_integrity_coverage(tmp_path: Path) -> None:
    _workspace(tmp_path, nested_checksum_overclaim=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-ARCHIVE-CHECKSUM-COVERAGE" in codes
    assert "SUPPORT-ARCHIVE-MANIFEST-COVERAGE" in codes


def test_support_audit_accepts_explicit_checksum_self_exclusion(tmp_path: Path) -> None:
    _workspace(tmp_path, nested_checksum_qualified_claim=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is True


def test_support_audit_failure_blocks_quality_gate(tmp_path: Path) -> None:
    _workspace(tmp_path, process_prose=True)

    result = record_quality_gate(
        PAPER_ID,
        venue_type="journal",
        score=8,
        decision="accept",
        revision_rounds=0,
        root=tmp_path,
    )

    assert result["passed"] is False
    assert result["status"] == "revision_required"
    assert any("SUPPORT-PROCESS-NARRATIVE" in value for value in result["unresolved_blockers"])
    metadata = load_paper_metadata(PAPER_ID, tmp_path)
    assert metadata["writing_release"]["status"] == "revision_required"


def test_support_audit_rejects_stale_version_inside_exact_archive(tmp_path: Path) -> None:
    _workspace(tmp_path, archived_version="0.9.0")

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-SOURCE-VERSION" in codes
    assert "SUPPORT-ARCHIVE-STALE-VERSION" in codes
    assert "SUPPORT-ARCHIVE-VERSION-MISSING" in codes


def test_support_audit_rejects_release_narrative_inside_exact_archive(tmp_path: Path) -> None:
    _workspace(tmp_path, archive_process_prose=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-ARCHIVE-PROCESS-NARRATIVE" in codes
    assert "SUPPORT-ARCHIVE-DRAFT-PUBLIC-CLAIM" in codes


def test_support_audit_rejects_stale_public_support_path_in_manuscript(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace(
            "The archive contains the exact certificate and replay instructions.",
            "The project is rooted at \\path{evidence/public-support-v0.9.0/}.",
        ),
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is False
    assert any(
        item["code"] == "SUPPORT-PUBLIC-DIRECTORY-VERSION"
        for item in result["errors"]
    )


def test_support_audit_rejects_embedded_prior_evaluation(tmp_path: Path) -> None:
    _workspace(tmp_path, archive_evaluation_projection=True)

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is False
    assert any(
        item["code"] == "SUPPORT-ARCHIVE-EVALUATION-PROJECTION"
        for item in result["errors"]
    )


def test_support_audit_rejects_printed_path_missing_from_archive(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace(
            "The archive contains the exact certificate and replay instructions.",
            "The support archive contains \\path{missing-certificate.json}.",
        ),
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is False
    assert any(
        item["code"] == "SUPPORT-ARCHIVE-PATH-MISSING"
        for item in result["errors"]
    )


def test_support_audit_rejects_nested_path_described_as_archive_root(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace(
            "The archive contains the exact certificate and replay instructions.",
            "The support archive contains \\path{certificate.json} at its archive root.",
        ),
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is False
    assert any(
        item["code"] == "SUPPORT-ARCHIVE-PATH-NOT-AT-ROOT"
        for item in result["errors"]
    )
