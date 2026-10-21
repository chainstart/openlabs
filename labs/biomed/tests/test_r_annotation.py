from __future__ import annotations

import hashlib
import subprocess

import pytest
from tools.repair_r_annotation import repair


def test_annotation_repair_rejects_changed_archive_before_running_r(tmp_path, monkeypatch):
    archive = tmp_path / "GenomeInfoDbData_1.2.13.tar.gz"
    archive.write_bytes(b"corrupt software fixture")

    def unexpected_process(*args, **kwargs):
        pytest.fail("R must not execute an archive that fails its checksum")

    monkeypatch.setattr("tools.repair_r_annotation.subprocess.run", unexpected_process)
    with pytest.raises(ValueError, match="checksum mismatch"):
        repair(archive, tmp_path / "prefix")


def test_annotation_repair_requires_namespace_after_successful_install_exit(tmp_path, monkeypatch):
    archive = tmp_path / "fixture.tar.gz"
    body = b"synthetic installer fixture; never executed"
    archive.write_bytes(body)
    prefix = tmp_path / "prefix"
    (prefix / "conda-meta").mkdir(parents=True)
    (prefix / "conda-meta/history").touch()
    lock = {
        "filename": archive.name,
        "upstream_md5": hashlib.md5(body, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "package": "FixtureOnly",
        "version": "0.0.0",
    }
    monkeypatch.setattr("tools.repair_r_annotation.read_json", lambda path: lock)
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0 if len(commands) == 1 else 1,
            stdout="",
            stderr="namespace missing",
        )

    monkeypatch.setattr("tools.repair_r_annotation.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="namespace missing"):
        repair(archive, prefix)
    assert len(commands) == 2
