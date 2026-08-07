from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.source_equivalence import (  # noqa: E402
    verify_source_equivalence_certificate,
)


PROTOCOL = ROOT / "analysis/protocols/llzto_source_equivalence_v1.json"
CERTIFICATE = ROOT / "analysis/audits/llzto_source_equivalence_v1.json"


def test_committed_source_equivalence_certificate_is_hash_bound_and_exact():
    certificate = verify_source_equivalence_certificate(PROTOCOL, CERTIFICATE)
    assert certificate["status"] == "pass"
    comparison = certificate["transport_recomputation"]
    assert comparison["all_legacy_transport_fields_exactly_equal"] is True
    assert comparison["maximum_absolute_legacy_numeric_difference"] == 0.0
    assert comparison["paired_block_count"] == 5
    assert certificate["structure_preparation"]["exact_fingerprint_match"] is True
    assert all(certificate["checks"].values())


def test_source_equivalence_certificate_rejects_tampering(tmp_path):
    payload = json.loads(CERTIFICATE.read_text(encoding="utf-8"))
    payload["transport_recomputation"][
        "all_legacy_transport_fields_exactly_equal"
    ] = False
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="certificate fingerprint mismatch"):
        verify_source_equivalence_certificate(PROTOCOL, changed)
