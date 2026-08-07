from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.provenance import sha256_file  # noqa: E402
from matfactory.research_attestation import (  # noqa: E402
    validate_formal_model_identity,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_formal_identity_accepts_universal_and_finetuned_without_aliasing(tmp_path):
    universal_path = tmp_path / "universal.json"
    universal_protocol = {"campaign_id": "universal-campaign"}
    _write(universal_path, universal_protocol)
    universal_manifest = {
        "config": {
            "model_name": "CHGNet-default",
            "expected_model_state_dict_sha256": "universal-state",
            "provenance": {
                "campaign_protocol_sha256": sha256_file(universal_path)
            },
        },
        "model": {"state_dict_sha256": "universal-state"},
    }

    universal_checks = validate_formal_model_identity(
        universal_manifest,
        universal_protocol,
        campaign_protocol_path=universal_path,
        branch="universal",
    )

    assert all(universal_checks.values())

    model_path = tmp_path / "model.pth.tar"
    report_path = tmp_path / "training.json"
    model_path.write_bytes(b"fine-model")
    report_path.write_text("{}", encoding="utf-8")
    artifact = {
        "path": str(model_path),
        "sha256": sha256_file(model_path),
        "state_dict_sha256": "fine-state",
        "training_report_path": str(report_path),
        "training_report_sha256": sha256_file(report_path),
    }
    fine_path = tmp_path / "fine.json"
    fine_protocol = {
        "campaign_id": "fine-campaign",
        "derived_model_artifact": artifact,
    }
    _write(fine_path, fine_protocol)
    fine_manifest = {
        "config": {
            "model_name": "CHGNet-llzto-finetuned-v1",
            "expected_model_state_dict_sha256": "fine-state",
            "provenance": {"campaign_protocol_sha256": sha256_file(fine_path)},
        },
        "model": {"state_dict_sha256": "fine-state"},
    }

    fine_checks = validate_formal_model_identity(
        fine_manifest,
        fine_protocol,
        campaign_protocol_path=fine_path,
        branch="finetuned",
    )

    assert all(fine_checks.values())
    cross_branch = validate_formal_model_identity(
        fine_manifest,
        fine_protocol,
        campaign_protocol_path=fine_path,
        branch="universal",
    )
    assert cross_branch["universal_model_name"] is False
    assert cross_branch["no_custom_model_artifact"] is False
