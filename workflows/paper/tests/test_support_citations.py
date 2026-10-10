import hashlib
import json
import zipfile
from pathlib import Path

import yaml
import pytest

from paper_writing.operations import record_quality_gate
from paper_writing.registry import load_paper_metadata
from paper_writing.support import build_support_archive
from paper_writing.support_citations import (
    _archive_filename_is_registered,
    _registered_source_checks,
    audit_manuscript_support,
)


PAPER_ID = "20260806-math-graph-support-citation-audit"


@pytest.mark.parametrize("outer", ["code-first-v1.0.0", "public-support-v1.0.0"])
def test_current_source_package_retains_legacy_component_version(tmp_path: Path, outer: str) -> None:
    publication = {"source_files": [
        f"papers/{PAPER_ID}/{outer}/legacy/public-support-v0.9.0/code/verify.py"
    ]}
    assert not _registered_source_checks(publication, version="1.0.0", root=tmp_path)


@pytest.mark.parametrize("outer", ["code-first-v0.9.0", "public-support-v0.9.0"])
def test_stale_outer_source_package_stays_blocked(tmp_path: Path, outer: str) -> None:
    publication = {"source_files": [
        f"papers/{PAPER_ID}/{outer}/legacy/public-support-v1.0.0/code/verify.py"
    ]}
    issues = _registered_source_checks(publication, version="1.0.0", root=tmp_path)
    assert [item["code"] for item in issues] == ["SUPPORT-SOURCE-VERSION"]
    assert outer in issues[0]["message"]


def test_explicit_material_version_keeps_draft_checks_strict(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / "registry/papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text())
    record["version"] = "1.0.3"
    record["support"]["publication"]["release_version"] = "1.0.0"
    path.write_text(yaml.safe_dump(record))
    assert audit_manuscript_support(PAPER_ID, root=tmp_path)["valid"]
    record["support"]["publication"]["release_version"] = "1.0.1"
    path.write_text(yaml.safe_dump(record))
    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    assert not result["valid"]
    assert any(item["code"] == "SUPPORT-DRAFT-VERSION" for item in result["errors"])


@pytest.mark.parametrize("phrase", ["supporting collection", "support source collection"])
def test_cited_support_collection_is_a_material_mention(tmp_path: Path, phrase: str) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript/main.tex"
    main.write_text(main.read_text().replace("supporting materials", phrase))
    assert audit_manuscript_support(PAPER_ID, root=tmp_path)["valid"]
    main.write_text(main.read_text().replace(r"\citep{supportRecord}", ""))
    errors = audit_manuscript_support(PAPER_ID, root=tmp_path)["errors"]
    assert any(item["code"] == "SUPPORT-CITATION-MISSING" for item in errors)


def test_collection_without_support_identity_stays_blocked(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript/main.tex"
    main.write_text(r"\documentclass{article}\begin{document}An accompanying collection.\end{document}")
    errors = audit_manuscript_support(PAPER_ID, root=tmp_path)["errors"]
    assert any(item["code"] == "SUPPORT-MANUSCRIPT-CITATION-REQUIRED" for item in errors)


def _write_settings(root: Path) -> None:
    (root / "registry" / "papers").mkdir(parents=True)
    (root / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
require_registration: true
support_publication:
  default_mode: zenodo_only
  default_license: cc-by-4.0
  gates:
    before_review:
      minimum_status: draft
      require_version_doi: true
      require_manuscript_citation: true
    before_handoff:
      minimum_status: published
      require_version_doi: true
      require_quality_gate_package_binding: true
  not_required:
    require_reason: true
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
    creator_names: tuple[str, ...] = ("Ada Lovelace",),
    include_citation: bool = False,
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
    if include_citation:
        citation = public_source / "CITATION.cff"
        citation.write_text(yaml.safe_dump({
            "cff-version": "1.2.0", "message": "Cite this Zenodo supporting-material version.",
            "title": title, "version": archived_version, "doi": doi,
            "authors": [{"given-names": name.rsplit(" ", 1)[0], "family-names": name.rsplit(" ", 1)[1]} for name in creator_names],
        }))
        release_sources.append(citation)
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
  author = {""" + " and ".join(creator_names) + """},
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
        "authors": [{"name": name} for name in creator_names],
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
                    "creators": [{"name": name.rsplit(" ", 1)[1] + ", " + name.rsplit(" ", 1)[0]} for name in creator_names],
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


@pytest.mark.parametrize("case, passes", [
    ("published_permutation", True),
    ("draft_permutation", False),
    ("published_changed_member", False),
    ("published_changed_record_order", False),
    ("published_missing_record_creators", False),
])
def test_support_archive_keeps_published_creator_order(
    tmp_path: Path, case: str, passes: bool,
) -> None:
    _workspace(tmp_path, creator_names=("Ada Lovelace", "Charles Babbage"), include_citation=True)
    path = tmp_path / "registry/papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text())
    publication = record["support"]["publication"]
    archive = tmp_path / publication["package_files"][0]
    original_archive = archive.read_bytes()
    record["authors"].reverse()
    if case != "draft_permutation":
        publication["status"] = "published"
        publication["version_doi"] = publication["zenodo"]["reserved_version_doi"]
    if case == "published_changed_member":
        record["authors"][0]["name"] = "Grace Hopper"
    elif case == "published_changed_record_order":
        publication["zenodo"]["creators"].reverse()
    elif case == "published_missing_record_creators":
        publication["zenodo"].pop("creators")
    path.write_text(yaml.safe_dump(record, sort_keys=False))

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is passes, result["errors"]
    codes = {item["code"] for item in result["errors"]}
    assert ("SUPPORT-ARCHIVE-IDENTITY-CREATORS" in codes) is (not passes)
    assert archive.read_bytes() == original_archive


def test_support_audit_accepts_configured_default_license(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    publication = record["support"]["publication"]
    publication.pop("license", None)
    publication["zenodo"].pop("license", None)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)

    assert result["valid"] is True
    assert "SUPPORT-LICENSE-MISSING" not in {
        item["code"] for item in result["errors"]
    }


def test_support_audit_rejects_planned_record_when_prepared_doi_is_required(
    tmp_path: Path,
) -> None:
    _workspace(tmp_path)
    path = tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    publication = record["support"]["publication"]
    publication["status"] = "planned"
    publication.pop("version_doi", None)
    publication.pop("record_url", None)
    publication.pop("draft_receipt", None)
    publication.pop("package_files", None)
    publication.pop("package_sha256", None)
    publication.pop("package_size", None)
    publication.pop("zenodo", None)
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-STATUS-BEFORE-REVIEW" in codes
    assert "SUPPORT-DOI-MISSING" in codes


def test_support_audit_requires_manuscript_citation_under_policy(
    tmp_path: Path,
) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    main.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Finite calculations were performed.\n"
        "\\section*{Data and code availability}\n"
        "The calculations are reproducible from the stated procedures.\n"
        "\\bibliography{references}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    codes = {item["code"] for item in result["errors"]}

    assert result["valid"] is False
    assert "SUPPORT-MANUSCRIPT-CITATION-REQUIRED" in codes
    assert "SUPPORT-CITATION-MISSING" in codes


def test_not_required_mode_needs_configured_reason(tmp_path: Path) -> None:
    _workspace(tmp_path)
    path = tmp_path / "registry" / "papers" / f"{PAPER_ID}.yaml"
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    publication = record["support"]["publication"]
    publication["mode"] = "not_required"
    publication["status"] = "planned"
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")

    missing = audit_manuscript_support(PAPER_ID, root=tmp_path)
    assert missing["valid"] is False
    assert {item["code"] for item in missing["errors"]} == {
        "SUPPORT-NOT-REQUIRED-REASON"
    }

    publication["not_required_reason"] = "The paper has no external computational artifacts."
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    accepted = audit_manuscript_support(PAPER_ID, root=tmp_path)
    assert accepted["valid"] is True


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


def test_historical_experiment_archive_is_not_release_history(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace(
        "The archive contains the exact certificate and replay instructions.",
        "The historical archive provides a distinct comparison. Its 19 retained "
        "predictors used calibration labels for refitting.\n\n"
        "\\appendix\n\\section{Historical archive and diagnostic corrections}\n"
        "The retained predictors are conditional on calibration-label reuse.",
    ), encoding="utf-8")
    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    assert "SUPPORT-PROCESS-NARRATIVE" not in {item["code"] for item in result["errors"]}


def test_local_table_filename_is_not_release_history(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text()
    main.write_text(text.replace(
        "The archive contains the exact certificate and replay instructions.",
        r"The per-cell evidence tables \path{all-new-cells.csv} and "
        r"\path{all-head-only-cells.csv} are separately retained in "
        r"\path{support-materials/controlled-and-head-only-v1.0.3/}.",
    ))
    codes = {item["code"] for item in audit_manuscript_support(PAPER_ID, root=tmp_path)["errors"]}
    assert "SUPPORT-PROCESS-NARRATIVE" not in codes
    assert "SUPPORT-ARCHIVE-PATH-MISSING" in codes


def test_real_release_history_around_path_remains_blocked(tmp_path: Path) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    main.write_text(main.read_text().replace(
        "The archive contains the exact certificate and replay instructions.",
        r"The previous support version was replaced by \path{certificate.json}.",
    ))
    codes = {item["code"] for item in audit_manuscript_support(PAPER_ID, root=tmp_path)["errors"]}
    assert "SUPPORT-PROCESS-NARRATIVE" in codes


@pytest.mark.parametrize("narration", [
    "The previous archive was replaced by this deposited record.",
    "The earlier published archive was superseded by this record.",
])
def test_previous_archive_replacement_remains_release_history(tmp_path: Path, narration: str) -> None:
    _workspace(tmp_path)
    main = tmp_path / "papers" / PAPER_ID / "manuscript" / "main.tex"
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace(
        "The archive contains the exact certificate and replay instructions.",
        narration,
    ), encoding="utf-8")
    result = audit_manuscript_support(PAPER_ID, root=tmp_path)
    assert "SUPPORT-PROCESS-NARRATIVE" in {item["code"] for item in result["errors"]}


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
