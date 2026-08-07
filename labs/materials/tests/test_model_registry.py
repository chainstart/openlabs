from __future__ import annotations

import json
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.model_registry import (
    freeze_model_registry,
    load_model_registry_protocol,
)


def _protocol(tmp_path: Path, source: Path) -> Path:
    payload = {
        "schema_version": "1.0",
        "registry_id": "test-models-v1",
        "root_dir": str(tmp_path / "frozen"),
        "models": [
            {
                "model_id": "first",
                "family": "family-a",
                "package": "numpy",
                "expected_package_version": version("numpy"),
                "source_type": "local-file",
                "source": str(source),
                "filename": "first.model",
                "license_id": "BSD-3-Clause",
                "training_lineage": "test lineage",
                "intended_use": "test only",
            },
            {
                "model_id": "second",
                "family": "family-b",
                "package": "numpy",
                "expected_package_version": version("numpy"),
                "source_type": "local-file",
                "source": str(source),
                "filename": "second.model",
                "license_id": "MIT",
                "training_lineage": "test lineage",
                "intended_use": "test only",
            },
        ],
    }
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_freezes_and_reuses_byte_identical_models(tmp_path):
    source = tmp_path / "source.model"
    source.write_bytes(b"model-weights")
    protocol = _protocol(tmp_path, source)
    first = freeze_model_registry(protocol)
    second = freeze_model_registry(protocol)
    assert first == second
    assert len(first["models"]) == 2
    assert (
        first["models"][0]["artifact_sha256"] == first["models"][1]["artifact_sha256"]
    )


def test_registry_detects_artifact_mutation(tmp_path):
    source = tmp_path / "source.model"
    source.write_bytes(b"model-weights")
    protocol = _protocol(tmp_path, source)
    manifest = freeze_model_registry(protocol)
    Path(manifest["models"][0]["artifact_path"]).write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed or vanished"):
        freeze_model_registry(protocol)


def test_registry_requires_two_families(tmp_path):
    source = tmp_path / "source.model"
    source.write_bytes(b"model-weights")
    protocol = _protocol(tmp_path, source)
    payload = json.loads(protocol.read_text(encoding="utf-8"))
    payload["models"][1]["family"] = "family-a"
    protocol.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="two model families"):
        load_model_registry_protocol(protocol)
