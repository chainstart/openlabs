from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.discovery_dft import (
    load_dft_confirmation_protocol,
    materialize_sssp_manifest,
    prepare_discovery_dft,
)
from matfactory.provenance import sha256_file

PROTOCOL = ROOT / "analysis/protocols/hidden_order_dft_confirmation_v1.json"


def test_frozen_dft_confirmation_is_disabled_and_prepare_only():
    protocol = load_dft_confirmation_protocol(PROTOCOL)
    assert not protocol.enabled
    assert protocol.kpoint_cutoff_multiplier == 1.4
    assert protocol.physics_review["approved_model"] == "unreviewed"
    with pytest.raises(RuntimeError, match="disabled"):
        prepare_discovery_dft(PROTOCOL)


def test_kpoint_cutoff_can_use_a_converged_lower_ladder_entry(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["numerics"]["kpoint_cutoff_multiplier"] = 1.0
    amended = tmp_path / "amended.json"
    amended.write_text(json.dumps(payload), encoding="utf-8")
    assert load_dft_confirmation_protocol(amended).kpoint_cutoff_multiplier == 1.0


def test_sssp_materializer_extracts_only_requested_hash_checked_files(tmp_path):
    contents = {"Li": b"Li UPF\n", "O": b"O UPF\n", "Fe": b"Fe UPF\n"}
    index = {
        element: {
            "filename": f"{element}.UPF",
            "md5": hashlib.md5(value, usedforsecurity=False).hexdigest(),
            "pseudopotential": "test",
            "cutoff_wfc": 40.0,
            "cutoff_rho": 320.0,
        }
        for element, value in contents.items()
    }
    index_path = tmp_path / "index.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    archive_path = tmp_path / "pseudos.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for element, value in contents.items():
            info = tarfile.TarInfo(f"./{element}.UPF")
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    manifest, manifest_path = materialize_sssp_manifest(
        {"Li", "O"},
        index_path=index_path,
        index_sha256=sha256_file(index_path),
        archive_path=archive_path,
        archive_sha256=sha256_file(archive_path),
        output_dir=tmp_path / "selected",
    )
    assert set(manifest["elements"]) == {"Li", "O"}
    assert manifest_path.is_file()
    assert not (tmp_path / "selected/Fe.UPF").exists()


def test_sssp_materializer_rejects_archive_hash_mismatch(tmp_path):
    index_path = tmp_path / "index.json"
    index_path.write_text("{}", encoding="utf-8")
    archive_path = tmp_path / "pseudos.tar.gz"
    with tarfile.open(archive_path, "w:gz"):
        pass
    with pytest.raises(RuntimeError, match="archive hash mismatch"):
        materialize_sssp_manifest(
            {"Li"},
            index_path=index_path,
            index_sha256=sha256_file(index_path),
            archive_path=archive_path,
            archive_sha256="0" * 64,
            output_dir=tmp_path / "selected",
        )
