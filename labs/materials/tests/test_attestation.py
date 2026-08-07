from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.attestation import (  # noqa: E402
    _write_attestation,
    compare_manifest_outputs,
    compare_manuscript_outputs,
    parse_pytest_pass_count,
)
from matfactory.provenance import fingerprint, sha256_file  # noqa: E402


def test_pytest_summary_parser_uses_final_pass_count():
    output = "progress\n252 passed, 38 warnings in 42.36s\n"
    assert parse_pytest_pass_count(output) == 252
    with pytest.raises(ValueError, match="no passed-test summary"):
        parse_pytest_pass_count("1 failed in 0.1s")


def test_attestation_is_fingerprinted_and_immutable(tmp_path):
    destination = tmp_path / "attestation.json"
    payload = _write_attestation(
        destination,
        {"schema_version": "1.0", "attestation_kind": "test", "pass": True},
    )
    unsigned = dict(payload)
    stored = unsigned.pop("attestation_fingerprint")
    assert stored == fingerprint(unsigned)
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        _write_attestation(destination, {"pass": True})


def _manifest(tmp_path: Path, prefix: str, content: bytes) -> dict:
    figure = tmp_path / f"{prefix}.svg"
    table = tmp_path / f"{prefix}.csv"
    source = tmp_path / f"{prefix}.source"
    figure.write_bytes(content)
    table.write_bytes(content + b"-table")
    source.write_bytes(b"source")
    payload = {
        "figures": [
            {
                "figure_id": "fig01",
                "outputs": [
                    {
                        "format": "svg",
                        "path": str(figure),
                        "sha256": sha256_file(figure),
                    }
                ],
            }
        ],
        "tables": [
            {
                "table_id": "table01",
                "outputs": [
                    {
                        "format": "csv",
                        "path": str(table),
                        "sha256": sha256_file(table),
                    }
                ],
            }
        ],
        "sources": [{"path": str(source), "sha256": sha256_file(source)}],
    }
    payload["manifest_fingerprint"] = fingerprint(payload)
    return payload


def test_clean_regeneration_comparison_uses_logical_ids_not_paths(tmp_path):
    expected = _manifest(tmp_path, "expected", b"same")
    regenerated = _manifest(tmp_path, "regenerated", b"same")
    comparison = compare_manifest_outputs(expected, regenerated)
    assert comparison["all_hashes_match"] is True
    assert comparison["n_expected_outputs"] == 2

    changed = _manifest(tmp_path, "changed", b"different")
    comparison = compare_manifest_outputs(expected, changed)
    assert comparison["all_hashes_match"] is False
    assert set(comparison["mismatches"]) == {
        "figures/fig01/svg",
        "tables/table01/csv",
    }


def _manuscript_manifest(tmp_path: Path, prefix: str, content: bytes) -> dict:
    protocol = tmp_path / f"{prefix}.protocol.json"
    publication = tmp_path / f"{prefix}.publication.json"
    protocol.write_text("{}\n")
    publication.write_text("{}\n")
    documents = []
    for document_id in ("main", "supplement", "data_availability"):
        path = tmp_path / f"{prefix}.{document_id}.md"
        path.write_bytes(content + document_id.encode())
        documents.append(
            {
                "document_id": document_id,
                "path": str(path),
                "sha256": sha256_file(path),
            }
        )
    payload = {
        "manuscript_gate_pass": True,
        "manuscript_protocol_path": str(protocol),
        "manuscript_protocol_sha256": sha256_file(protocol),
        "publication_manifest_path": str(publication),
        "publication_manifest_sha256": sha256_file(publication),
        "documents": documents,
    }
    payload["manifest_fingerprint"] = fingerprint(payload)
    return payload


def test_clean_manuscript_comparison_uses_logical_ids_not_paths(tmp_path):
    expected = _manuscript_manifest(tmp_path, "expected", b"same")
    regenerated = _manuscript_manifest(tmp_path, "regenerated", b"same")
    comparison = compare_manuscript_outputs(expected, regenerated)
    assert comparison["all_hashes_match"] is True
    assert comparison["n_expected_outputs"] == 3

    changed = _manuscript_manifest(tmp_path, "changed", b"different")
    comparison = compare_manuscript_outputs(expected, changed)
    assert comparison["all_hashes_match"] is False
    assert set(comparison["mismatches"]) == {
        "documents/main",
        "documents/supplement",
        "documents/data_availability",
    }
