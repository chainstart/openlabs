import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest

import paper_writing.zenodo as zenodo
from paper_writing.__main__ import main
from paper_writing.handoff import manuscript_snapshot_sha256
from paper_writing.operations import record_quality_gate
from paper_writing.registry import load_paper_metadata
from paper_writing.support import (
    SupportPackageError,
    build_support_archive,
    md5_file,
    resolve_support_sources,
    verify_support_archive,
)
from paper_writing.zenodo import (
    ZenodoClient,
    create_version_with_files,
    prepare_zenodo_release,
    publish_zenodo_release,
    verify_deposition_files,
    verify_prepared_zenodo_draft,
)


def test_delete_file_uses_deposition_file_endpoint() -> None:
    def delete(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.raw_path == (
            b"/api/deposit/depositions/42/files/inherited%2Farchive"
        )
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(204)

    http_client = httpx.Client(transport=httpx.MockTransport(delete))
    try:
        client = ZenodoClient("sandbox", "test-token", client=http_client)
        result = client.delete_file(42, "inherited/archive")
    finally:
        http_client.close()

    assert result == {
        "deleted": True,
        "deposition_id": 42,
        "file_id": "inherited/archive",
    }


def test_transient_metadata_timeout_recovers_only_after_identity_readback() -> None:
    metadata = {
        "title": "Current support",
        "version": "1.2.4",
        "upload_type": "other",
        "publication_date": "2026-08-07",
        "access_right": "open",
        "license": "cc-by-4.0",
        "creators": [{"name": "Lovelace, Ada"}],
    }
    draft = {
        "id": 42,
        "submitted": False,
        "metadata": {
            **metadata,
            "prereserve_doi": {"doi": "10.5281/zenodo.42", "recid": 42},
        },
    }

    class TimeoutAfterAcceptedPut:
        def update_metadata(
            self,
            deposition_id: int | str,
            submitted: dict[str, Any],
        ) -> dict[str, Any]:
            assert deposition_id == 42
            assert submitted == metadata
            raise zenodo.ZenodoError(
                "Failed to update Zenodo deposition metadata: HTTP 504: timeout"
            )

        def get_deposition(self, deposition_id: int | str) -> dict[str, Any]:
            assert deposition_id == 42
            return draft

    result = zenodo._update_metadata_with_transient_readback(
        TimeoutAfterAcceptedPut(),
        draft,
        {},
        metadata,
    )

    assert result == draft


def test_metadata_readback_does_not_hide_nontransient_errors() -> None:
    draft = {
        "id": 42,
        "submitted": False,
        "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.42"}},
    }

    class UnauthorizedUpdate:
        def update_metadata(
            self,
            deposition_id: int | str,
            submitted: dict[str, Any],
        ) -> dict[str, Any]:
            raise zenodo.ZenodoError(
                "Failed to update Zenodo deposition metadata: HTTP 401: unauthorized"
            )

        def get_deposition(self, deposition_id: int | str) -> dict[str, Any]:
            raise AssertionError("non-transient failures must not be read back")

    with pytest.raises(zenodo.ZenodoError, match="HTTP 401"):
        zenodo._update_metadata_with_transient_readback(
            UnauthorizedUpdate(),
            draft,
            {},
            {},
        )


def test_new_version_removes_inherited_files_before_upload(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    package = tmp_path / "support-v2.zip"
    package.write_bytes(b"new support")
    events: list[tuple[str, Any]] = []

    class FakeZenodoClient:
        def __init__(self, environment: str, token: str) -> None:
            events.append(("init", (environment, token)))

        def __enter__(self) -> "FakeZenodoClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def new_version(self, deposition_id: int | str) -> dict[str, Any]:
            events.append(("new_version", deposition_id))
            return {
                "id": 84,
                "files": [
                    {"id": "old-file-1", "filename": "support-v1.zip"},
                    {"filename": "entry-without-id"},
                ],
            }

        def update_metadata(
            self,
            deposition_id: int | str,
            metadata: dict[str, Any],
        ) -> dict[str, Any]:
            events.append(("metadata", deposition_id))
            return {
                "id": 84,
                "files": [
                    {"id": "old-file-1", "filename": "support-v1.zip"},
                    {"filename": "entry-without-id"},
                ],
            }

        def delete_file(
            self,
            deposition_id: int | str,
            file_id: int | str,
        ) -> dict[str, Any]:
            events.append(("delete", (deposition_id, file_id)))
            return {"deleted": True, "file_id": str(file_id)}

        def upload_file(
            self,
            draft: dict[str, Any],
            path: str | Path,
        ) -> dict[str, Any]:
            events.append(("upload", (draft["id"], Path(path).name)))
            return {"key": Path(path).name}

    monkeypatch.setattr(zenodo, "ZenodoClient", FakeZenodoClient)
    record = {
        "id": "paper-test",
        "title": "Test manuscript",
        "authors": {"names": ["Ada Lovelace"]},
        "support": {
            "publication": {
                "mode": "zenodo_only",
                "zenodo": {"environment": "sandbox"},
            }
        },
    }

    result = create_version_with_files(
        record,
        42,
        [package],
        environment="sandbox",
        token="test-token",
        repo_root=tmp_path,
    )

    assert events[-2:] == [
        ("delete", (84, "old-file-1")),
        ("upload", (84, "support-v2.zip")),
    ]
    assert result["removed_inherited_files"] == [
        {"deleted": True, "file_id": "old-file-1"}
    ]


def test_current_paper_version_overrides_stale_zenodo_draft_state() -> None:
    record = {
        "id": "20260802mathgraph0001",
        "title": "Versioned manuscript",
        "version": "0.1.3",
        "authors": {"names": ["Ada Lovelace"]},
        "support": {
            "publication": {
                "mode": "zenodo_only",
                "zenodo": {"version": "0.1.2"},
            }
        },
    }

    metadata = zenodo.build_zenodo_metadata(record)

    assert metadata["version"] == "0.1.3"


def test_prepare_identity_moves_old_public_record_out_of_active_fields() -> None:
    publication = {
        "status": "published",
        "version_doi": "10.5281/zenodo.100",
        "concept_doi": "10.5281/zenodo.99",
        "record_url": "https://zenodo.org/records/100",
        "public_download_verified": True,
    }
    registered = {
        "record_id": 100,
        "version": "1.0.0",
        "published_at": "2026-08-01T00:00:00+00:00",
        "previous_published": {
            "version_doi": "10.5281/zenodo.98",
            "version": "0.9.0",
        },
    }

    zenodo._preserve_previous_published_identity(
        publication,
        registered,
        current_status="published",
        current_draft_doi="10.5281/zenodo.101",
    )

    assert registered["previous_published"] == {
        "version_doi": "10.5281/zenodo.100",
        "concept_doi": "10.5281/zenodo.99",
        "record_url": "https://zenodo.org/records/100",
        "record_id": 100,
        "published_at": "2026-08-01T00:00:00+00:00",
        "version": "1.0.0",
        "public_download_verified": True,
    }
    assert "record_id" not in registered
    assert "published_at" not in registered
    assert "public_download_verified" not in publication


def test_draft_identity_rejects_creator_mismatch() -> None:
    record = {
        "id": "20260802mathgraph0001",
        "title": "Four-author manuscript",
        "version": "0.1.3",
        "authors": {"names": ["Ada Lovelace", "Grace Hopper"]},
        "support": {"publication": {"mode": "zenodo_only", "license": "cc-by-4.0"}},
    }
    expected = zenodo.build_zenodo_metadata(record)
    deposition = {
        "id": 123,
        "metadata": {
            **expected,
            "creators": [{"name": "Lovelace, Ada"}],
            "prereserve_doi": {"doi": "10.5281/zenodo.123"},
        },
    }

    with pytest.raises(zenodo.ZenodoError, match="creators do not match"):
        zenodo._verify_draft_identity(
            record,
            {"zenodo": {"reserved_version_doi": "10.5281/zenodo.123"}},
            deposition,
        )


def test_support_archive_is_deterministic_and_self_verifying(tmp_path: Path) -> None:
    paper_id = "20260802-math-graph-opg1757-active-newton"
    evidence = tmp_path / "papers" / paper_id / "evidence"
    evidence.mkdir(parents=True)
    readme = evidence / "REPLAY.md"
    result = evidence / "certificate.json"
    readme.write_text("Run the exact verifier.\n", encoding="utf-8")
    result.write_text('{"verified": true}\n', encoding="utf-8")
    record = {
        "paper_id": paper_id,
        "title": "A deterministic support archive",
        "version": "0.1.2",
        "support": {"publication": {"license": "cc-by-4.0"}},
    }
    first = build_support_archive(
        record,
        [readme, result],
        repo_root=tmp_path,
        output=tmp_path / "first.zip",
        reserved_doi="10.5281/zenodo.123",
        origin_commit="a" * 40,
    )
    readme.touch()
    result.touch()
    second = build_support_archive(
        record,
        [readme, result],
        repo_root=tmp_path,
        output=tmp_path / "second.zip",
        reserved_doi="10.5281/zenodo.123",
        origin_commit="a" * 40,
    )

    assert first["archive_sha256"] == second["archive_sha256"]
    assert first["archive"].read_bytes() == second["archive"].read_bytes()
    verified = verify_support_archive(first["archive"])
    assert verified["paper_id"] == paper_id
    assert verified["paper_version"] == "0.1.2"
    assert verified["reserved_version_doi"] == "10.5281/zenodo.123"
    with zipfile.ZipFile(first["archive"]) as archive:
        assert any(name.endswith("/ZENODO_MANIFEST.json") for name in archive.namelist())
        manifest_name = next(
            name for name in archive.namelist() if name.endswith("/ZENODO_MANIFEST.json")
        )
        manifest = json.loads(archive.read(manifest_name))
        assert manifest["files"]
        assert all("repository_path" not in item for item in manifest["files"])
        assert all(
            item["archive_path"].startswith(f"{paper_id}-support-v0.1.2/")
            for item in manifest["files"]
        )
        assert any(name.endswith("/SHA256SUMS") for name in archive.namelist())
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_support_archive_verifier_ignores_nested_control_files(tmp_path: Path) -> None:
    paper_id = "20260802-math-graph-nested-support"
    evidence = tmp_path / "papers" / paper_id / "evidence"
    evidence.mkdir(parents=True)
    nested = evidence / "replay-kit.zip"
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("ZENODO_MANIFEST.json", "{}\n")
        archive.writestr("SHA256SUMS", "")
    record = {
        "paper_id": paper_id,
        "title": "A support archive containing a nested replay archive",
        "version": "1.0.0",
        "support": {"publication": {"license": "cc-by-4.0"}},
    }
    package = build_support_archive(
        record,
        [nested],
        repo_root=tmp_path,
        output=tmp_path / "outer.zip",
        reserved_doi="10.5281/zenodo.123",
        origin_commit="a" * 40,
    )

    verified = verify_support_archive(package["archive"])

    assert verified["paper_id"] == paper_id
    assert verified["paper_version"] == "1.0.0"


def test_support_sources_reject_credential_files(tmp_path: Path) -> None:
    secret = tmp_path / ".env.production"
    secret.write_text("TOKEN=do-not-package\n", encoding="utf-8")
    record = {
        "paper_id": "20260802mathgraph0001",
        "support": {"publication": {"source_files": [secret.name]}},
    }

    with pytest.raises(SupportPackageError, match="credential"):
        resolve_support_sources(record, repo_root=tmp_path)


def test_explicit_support_sources_replace_configured_version(tmp_path: Path) -> None:
    old = tmp_path / "evidence" / "public-support-v1.0.0" / "README.md"
    current = tmp_path / "evidence" / "public-support-v1.1.0" / "README.md"
    old.parent.mkdir(parents=True)
    current.parent.mkdir(parents=True)
    old.write_text("old\n", encoding="utf-8")
    current.write_text("current\n", encoding="utf-8")
    record = {
        "paper_id": "20260807mathgraph0001",
        "support": {"publication": {"source_files": [str(old.relative_to(tmp_path))]}},
    }

    resolved = resolve_support_sources(
        record,
        [current.parent],
        repo_root=tmp_path,
    )

    assert resolved == [current.resolve()]


def test_remote_checksum_mismatch_blocks_release(tmp_path: Path) -> None:
    package = tmp_path / "support.zip"
    package.write_bytes(b"verified locally")
    deposition = {
        "files": [
            {
                "filename": package.name,
                "filesize": package.stat().st_size,
                "checksum": "md5:" + "0" * 32,
            }
        ]
    }

    with pytest.raises(zenodo.ZenodoError, match="checksum mismatch"):
        verify_deposition_files(deposition, [package])


def test_publish_release_stops_before_network_when_quality_gate_is_not_ready(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    paper_id = "20260802mathgraph0001"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
quality_gate:
  minimum_score: 6.0
""",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
title: Not ready
writing_release:
  status: revision_required
""",
        encoding="utf-8",
    )

    class NetworkMustNotRun:
        def __init__(self, *_: Any, **__: Any) -> None:
            raise AssertionError("Zenodo network client must not be created before the gate")

    monkeypatch.setattr(zenodo, "ZenodoClient", NetworkMustNotRun)
    with pytest.raises(zenodo.ZenodoError, match="not release-ready"):
        publish_zenodo_release(
            paper_id,
            environment="production",
            token="test-token",
            repo_root=tmp_path,
        )


def _gate_only_release_repo(tmp_path: Path, paper_id: str) -> Path:
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        "schema_version: ara.paper_writing.registry.v1\nquality_gate:\n  minimum_score: 6.0\n",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"paper_id: {paper_id}\ntitle: Not ready\nwriting_release:\n  status: revision_required\n",
        encoding="utf-8",
    )
    return settings


def test_production_release_needs_no_interactive_confirmation(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """The quality gate authorizes release, so no --confirm-* flag is required."""

    paper_id = "20260802mathgraph0001"
    settings = _gate_only_release_repo(tmp_path, paper_id)
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("OPENLABS_ENABLE_EXTERNAL_WRITES", "1")

    class NetworkMustNotRun:
        def __init__(self, *_: Any, **__: Any) -> None:
            raise AssertionError("Zenodo network client must not be created before the gate")

    monkeypatch.setattr(zenodo, "ZenodoClient", NetworkMustNotRun)
    exit_code = main(
        [
            "zenodo",
            "release",
            "--root",
            str(tmp_path),
            "--config",
            str(settings),
            "--paper-id",
            paper_id,
            "--environment",
            "production",
        ]
    )

    output = capsys.readouterr().out
    # It must fail on the gate, never on a missing confirmation flag.
    assert exit_code == 2
    assert "--confirm-production" not in output
    assert "not release-ready" in output


def test_release_still_rejects_mismatched_optional_paper_id_confirmation(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    paper_id = "20260802mathgraph0001"
    settings = _gate_only_release_repo(tmp_path, paper_id)
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("OPENLABS_ENABLE_EXTERNAL_WRITES", "1")

    exit_code = main(
        [
            "zenodo",
            "release",
            "--root",
            str(tmp_path),
            "--config",
            str(settings),
            "--paper-id",
            paper_id,
            "--environment",
            "production",
            "--confirm-paper-id",
            "20260802mathgraph0002",
        ]
    )

    assert exit_code == 2
    assert "must exactly match --paper-id" in capsys.readouterr().out


def test_production_prepare_still_requires_confirmation(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """Draft creation runs before the gate, so it keeps its production guard."""

    paper_id = "20260802mathgraph0001"
    settings = _gate_only_release_repo(tmp_path, paper_id)
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("OPENLABS_ENABLE_EXTERNAL_WRITES", "1")

    exit_code = main(
        [
            "zenodo",
            "prepare",
            "--root",
            str(tmp_path),
            "--config",
            str(settings),
            "--paper-id",
            paper_id,
            "--environment",
            "production",
        ]
    )

    assert exit_code == 2
    assert "--confirm-production" in capsys.readouterr().out


def test_legacy_cli_cannot_bypass_production_release_gate(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    paper_id = "20260802mathgraph0001"
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    settings = tmp_path / "registry" / "settings.yaml"
    settings.write_text(
        "schema_version: ara.paper_writing.registry.v1\ndefaults: {}\n",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"paper_id: {paper_id}\ntitle: Test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ZENODO_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("OPENLABS_ENABLE_EXTERNAL_WRITES", "1")

    exit_code = main(
        [
            "zenodo",
            "publish",
            "--root",
            str(tmp_path),
            "--config",
            str(settings),
            "--paper-id",
            paper_id,
            "--deposition-id",
            "123",
            "--environment",
            "production",
            "--confirm-production",
            "--confirm-paper-id",
            paper_id,
        ]
    )

    assert exit_code == 2
    assert "Direct production publish is disabled" in capsys.readouterr().out


def test_prepare_and_publish_release_bind_gate_git_and_remote_files(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    paper_id = "20260802mathgraph0001"
    manuscript = tmp_path / "papers" / paper_id / "manuscript"
    evidence = tmp_path / "papers" / paper_id / "evidence" / "release"
    manuscript.mkdir(parents=True)
    evidence.mkdir(parents=True)
    (manuscript / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    (manuscript / "main.pdf").write_bytes(b"%PDF-1.4 frozen")
    (evidence / "REPLAY.md").write_text("Replay instructions.\n", encoding="utf-8")
    certificate = evidence / "certificate.json"
    certificate.write_text('{"ok": true}\n', encoding="utf-8")
    snapshot = manuscript_snapshot_sha256(manuscript, manuscript / "main.pdf")
    registry = tmp_path / "registry" / "papers"
    registry.mkdir(parents=True)
    (tmp_path / "registry" / "settings.yaml").write_text(
        """schema_version: ara.paper_writing.registry.v1
support_publication:
  default_mode: zenodo_only
  zenodo_environment: sandbox
quality_gate:
  minimum_score: 6.0
  maximum_revision_rounds: 3
  conference_minimum_decision: weak_accept
  journal_minimum_decision: minor_revision
defaults: {}
""",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
title: Test gated Zenodo release
version: 0.1.2
manuscript_dir: papers/{paper_id}/manuscript
latest_pdf: papers/{paper_id}/manuscript/main.pdf
authors:
  - name: Ada Lovelace
writing_release:
  status: ready
  target_score: 6.0
  score: 7.0
  venue_type: journal
  decision: minor_revision
  reviewed_at: '2026-08-03T00:00:00+00:00'
  manuscript_snapshot_sha256: {snapshot}
  manuscript_version: 0.1.2
support:
  publication:
    mode: zenodo_only
    status: planned
    verification_files:
      - papers/{paper_id}/support-materials/legacy.zip.sha256
    source_files:
      - papers/{paper_id}/evidence/release
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "registry", "papers"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "support sources",
        ],
        cwd=tmp_path,
        check=True,
    )

    remote: dict[str, Any] = {
        "id": 123,
        "submitted": False,
        "files": [],
        "metadata": {},
        "links": {"html": "https://zenodo.org/uploads/123"},
    }

    class FakeReleaseClient:
        def __init__(self, environment: str, token: str) -> None:
            assert environment == "production"
            assert token == "test-token"

        def __enter__(self) -> "FakeReleaseClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def create_draft(self, metadata: dict[str, Any]) -> dict[str, Any]:
            remote["metadata"] = {
                **metadata,
                "prereserve_doi": {"doi": "10.5281/zenodo.123", "recid": 123},
            }
            return remote

        def get_deposition(self, deposition_id: int | str) -> dict[str, Any]:
            assert str(deposition_id) == "123"
            return remote

        def update_metadata(
            self,
            deposition_id: int | str,
            metadata: dict[str, Any],
        ) -> dict[str, Any]:
            remote["metadata"].update(metadata)
            return remote

        def delete_file(
            self,
            deposition_id: int | str,
            file_id: int | str,
        ) -> dict[str, Any]:
            remote["files"] = [item for item in remote["files"] if item["id"] != file_id]
            return {"deleted": True, "file_id": str(file_id)}

        def upload_file(
            self,
            draft: dict[str, Any],
            path: str | Path,
        ) -> dict[str, Any]:
            local = Path(path)
            item = {
                "id": local.name,
                "filename": local.name,
                "filesize": local.stat().st_size,
                "checksum": f"md5:{md5_file(local)}",
            }
            remote["files"].append(item)
            return item

        def publish(self, deposition_id: int | str) -> dict[str, Any]:
            remote.update(
                {
                    "submitted": True,
                    "doi": "10.5281/zenodo.123",
                    "record_id": 123,
                    "conceptrecid": 100,
                    "conceptdoi": "10.5281/zenodo.100",
                    "modified": "2026-08-03T01:02:03+00:00",
                    "links": {"html": "https://zenodo.org/records/123"},
                }
            )
            return remote

    monkeypatch.setattr(zenodo, "ZenodoClient", FakeReleaseClient)
    prepared = prepare_zenodo_release(
        paper_id,
        environment="production",
        token="test-token",
        repo_root=tmp_path,
        license_id="cc-by-4.0",
    )
    assert prepared["status"] == "draft"
    assert prepared["reserved_version_doi"] == "10.5281/zenodo.123"
    prepared_record = load_paper_metadata(paper_id, tmp_path)
    assert prepared_record["support"]["publication"]["package_sha256"]
    assert "verification_files" not in prepared_record["support"]["publication"]
    assert (
        prepared_record["support"]["publication"]["version_doi"]
        == "10.5281/zenodo.123"
    )
    assert (
        prepared_record["support"]["publication"]["zenodo"]["version_doi"]
        == "10.5281/zenodo.123"
    )
    assert prepared_record["support"]["publication"]["zenodo"]["publication_date"]
    prepared_zenodo = prepared_record["support"]["publication"]["zenodo"]
    assert prepared_zenodo["title"] == "Test gated Zenodo release: supporting materials"
    assert prepared_zenodo["creators"] == [{"name": "Lovelace, Ada"}]
    assert prepared_zenodo["metadata_source"].endswith("/deposit/depositions/123")
    assert prepared_zenodo["metadata_verified_at"]
    assert prepared_zenodo["remote_files_verified_at"]
    assert len(prepared_zenodo["remote_files"]) == 2
    assert {
        item["name"]: item["sha256"] for item in prepared_zenodo["remote_files"]
    } == {
        item["name"]: item["sha256"] for item in prepared["remote_files"]
    }
    assert Path(tmp_path / prepared["archive"]).is_file()
    draft_receipt = json.loads((tmp_path / prepared["receipt"]).read_text(encoding="utf-8"))
    assert draft_receipt["schema_version"] == "ara.paper_writing.zenodo_draft.v2"
    assert draft_receipt["submitted_metadata"]["creators"] == [
        {"name": "Lovelace, Ada"}
    ]
    assert draft_receipt["verified_remote_metadata"]["creators"] == [
        {"name": "Lovelace, Ada"}
    ]
    assert len(draft_receipt["submitted_metadata_sha256"]) == 64
    assert (
        draft_receipt["submitted_metadata_sha256"]
        == draft_receipt["verified_remote_metadata_sha256"]
    )
    verified_draft = verify_prepared_zenodo_draft(
        paper_id,
        environment="production",
        token="test-token",
        repo_root=tmp_path,
    )
    assert verified_draft["remote_state_changed"] is False
    assert verified_draft["reserved_version_doi"] == "10.5281/zenodo.123"
    assert len(verified_draft["remote_files"]) == 2
    gated = record_quality_gate(
        paper_id,
        venue_type="journal",
        score=7.0,
        decision="minor_revision",
        revision_rounds=2,
        root=tmp_path,
    )
    assert gated["passed"] is True
    assert (
        load_paper_metadata(paper_id, tmp_path)["writing_release"]["support_package_sha256"]
        == prepared_record["support"]["publication"]["package_sha256"]
    )

    subprocess.run(["git", "add", "registry", "papers"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "freeze Zenodo draft",
        ],
        cwd=tmp_path,
        check=True,
    )
    certificate.write_text('{"ok": false}\n', encoding="utf-8")
    subprocess.run(["git", "add", str(certificate)], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "change support source without rebuilding",
        ],
        cwd=tmp_path,
        check=True,
    )
    with pytest.raises(zenodo.ZenodoError, match="changed after the Zenodo draft"):
        publish_zenodo_release(
            paper_id,
            environment="production",
            token="test-token",
            repo_root=tmp_path,
        )
    assert remote["submitted"] is False
    certificate.write_text('{"ok": true}\n', encoding="utf-8")
    subprocess.run(["git", "add", str(certificate)], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ARA Test",
            "-c",
            "user.email=ara-test@example.invalid",
            "commit",
            "-qm",
            "restore prepared support source",
        ],
        cwd=tmp_path,
        check=True,
    )
    released = publish_zenodo_release(
        paper_id,
        environment="production",
        token="test-token",
        repo_root=tmp_path,
    )

    assert released["status"] == "published"
    assert released["version_doi"] == "10.5281/zenodo.123"
    assert released["commit_required"] is True
    published_record = load_paper_metadata(paper_id, tmp_path)
    publication = published_record["support"]["publication"]
    assert publication["status"] == "published"
    assert publication["release_binding"]["score"] == 7.0
    receipt = json.loads((tmp_path / released["receipt"]).read_text(encoding="utf-8"))
    assert receipt["package_sha256"] == publication["package_sha256"]
