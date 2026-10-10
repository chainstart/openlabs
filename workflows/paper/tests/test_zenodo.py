import json
from copy import deepcopy
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
    default_support_archive_path,
    md5_file,
    resolve_support_sources,
    support_sources_snapshot_sha256,
    verify_support_archive,
)


def test_support_source_fingerprint_ignores_release_directory_version_only(
    tmp_path: Path,
) -> None:
    old = tmp_path / "papers" / "paper" / "evidence" / "release" / "public-support-v1.0.0"
    new = tmp_path / "papers" / "paper" / "evidence" / "release" / "public-support-v1.0.1"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "claims.yaml").write_text("result: 42\n", encoding="utf-8")
    (new / "claims.yaml").write_text("result: 42\n", encoding="utf-8")
    old_record = {"support": {"publication": {"source_files": [str(old.relative_to(tmp_path))]}}}
    new_record = {"support": {"publication": {"source_files": [str(new.relative_to(tmp_path))]}}}

    baseline = support_sources_snapshot_sha256(old_record, repo_root=tmp_path)
    assert support_sources_snapshot_sha256(new_record, repo_root=tmp_path) == baseline

    (new / "claims.yaml").write_text("result: 43\n", encoding="utf-8")
    assert support_sources_snapshot_sha256(new_record, repo_root=tmp_path) != baseline
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


def test_get_deposition_requests_fresh_authenticated_state_only_on_get() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["cache-control"] == "no-cache, no-store"
        assert request.headers["pragma"] == "no-cache"
        return httpx.Response(200, json={"id": 42, "submitted": False, "files": []})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        client = ZenodoClient("sandbox", "test-token", client=http_client)
        assert client.get_deposition(42)["id"] == 42
        assert client.headers == {"Authorization": "Bearer test-token"}


def test_upload_delayed_visibility_rereads_once_without_reupload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "support.zip"
    package.write_bytes(b"exact content")
    item = {"filename": package.name, "filesize": package.stat().st_size,
            "checksum": "md5:" + md5_file(package)}
    methods = []
    pauses = []
    monkeypatch.setattr(zenodo.time, "sleep", pauses.append)

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT":
            assert "cache-control" not in request.headers
            assert "pragma" not in request.headers
            return httpx.Response(504, text="timeout")
        assert request.headers["cache-control"] == "no-cache, no-store"
        assert request.headers["pragma"] == "no-cache"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/api/deposit/depositions/42"
        return httpx.Response(200, json={"id": 42, "submitted": False,
            "files": [] if methods.count("GET") == 1 else [item]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        result = ZenodoClient("sandbox", "test-token", client=http_client).upload_file(
            {"id": 42, "links": {"bucket": "https://sandbox.zenodo.org/api/files/bucket"}}, package,
        )
    assert result["verified_upload_readback"]["sha256"] == zenodo.sha256_file(package)
    assert methods == ["PUT", "GET", "GET"]
    assert pauses == [0.5]


@pytest.mark.parametrize("problem", [
    "wrong_id", "published", "unknown_submission", "missing_inventory",
    "malformed_entry", "malformed_name", "wrong_size", "wrong_checksum",
    "malformed_checksum", "duplicate_file", "still_missing", "inexact_name",
])
def test_upload_fresh_reread_remains_bounded_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str,
) -> None:
    package = tmp_path / "support.zip"
    package.write_bytes(b"exact content")
    item = {"filename": package.name, "filesize": package.stat().st_size,
            "checksum": "md5:" + md5_file(package)}
    second = {"id": 42, "submitted": False, "files": [item]}
    if problem == "wrong_id": second["id"] = 43
    elif problem == "published": second["submitted"] = True
    elif problem == "unknown_submission": second.pop("submitted")
    elif problem == "missing_inventory": second.pop("files")
    elif problem == "malformed_entry": second["files"] = [None]
    elif problem == "malformed_name": item["filename"] = 123
    elif problem == "wrong_size": item["filesize"] += 1
    elif problem == "wrong_checksum": item["checksum"] = "md5:" + "0" * 32
    elif problem == "malformed_checksum": item["checksum"] = "not-a-checksum"
    elif problem == "duplicate_file": second["files"].append(dict(item))
    elif problem == "still_missing": second["files"] = []
    elif problem == "inexact_name": item["filename"] = " " + package.name + " "
    methods = []
    pauses = []
    monkeypatch.setattr(zenodo.time, "sleep", pauses.append)

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT": return httpx.Response(504, text="timeout")
        return httpx.Response(200, json={"id": 42, "submitted": False, "files": []}
                              if methods.count("GET") == 1 else second)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        with pytest.raises(zenodo.ZenodoError):
            ZenodoClient("sandbox", "test-token", client=http_client).upload_file(
                {"id": 42, "links": {"bucket": "https://sandbox.zenodo.org/api/files/bucket"}}, package,
            )
    assert methods == ["PUT", "GET", "GET"]
    assert pauses == [0.5]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_upload_transient_failure_requires_exact_persisted_file(tmp_path: Path, status: int) -> None:
    package = tmp_path / "support.zip.sha256"
    package.write_bytes(b"exact transferred content\n")
    remote_file = {"id": "file-1", "filename": package.name,
                   "filesize": package.stat().st_size, "checksum": "md5:" + md5_file(package)}
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer test-token"
        if request.method == "PUT":
            assert request.read() == package.read_bytes()
            return httpx.Response(status, text="gateway failure")
        assert request.method == "GET"
        return httpx.Response(200, json={"id": 42, "submitted": False,
                                        "files": [remote_file, {"filename": "other.zip"}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        client = ZenodoClient("sandbox", "test-token", client=http_client)
        result = client.upload_file({"id": 42, "links": {
            "bucket": "https://sandbox.zenodo.org/api/files/verified-bucket"}}, package)
    assert result["recovered_http_status"] == status
    assert result["verified_upload_readback"]["sha256"] == zenodo.sha256_file(package)
    assert calls == [("PUT", "/api/files/verified-bucket/support.zip.sha256"),
                     ("GET", "/api/deposit/depositions/42")]


@pytest.mark.parametrize("problem", ["wrong_id", "published", "unknown_submission", "missing_file",
                                    "wrong_size", "wrong_checksum", "duplicate_file",
                                    "missing_inventory", "malformed_entry", "malformed_name"])
def test_upload_readback_cannot_recover_unverified_content(
    tmp_path: Path, problem: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "support.zip"
    package.write_bytes(b"exact content")
    item = {"filename": package.name, "filesize": package.stat().st_size,
            "checksum": "md5:" + md5_file(package)}
    draft = {"id": 42, "submitted": False, "files": [item]}
    if problem == "wrong_id": draft["id"] = 43
    elif problem == "published": draft["submitted"] = True
    elif problem == "unknown_submission": draft.pop("submitted")
    elif problem == "missing_file": draft["files"] = []
    elif problem == "wrong_size": item["filesize"] += 1
    elif problem == "wrong_checksum": item["checksum"] = "md5:" + "0" * 32
    elif problem == "duplicate_file": draft["files"].append(dict(item))
    elif problem == "missing_inventory": draft.pop("files")
    elif problem == "malformed_entry": draft["files"] = [None]
    elif problem == "malformed_name": item["filename"] = 123
    methods = []
    pauses = []
    monkeypatch.setattr(zenodo.time, "sleep", pauses.append)

    def respond(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "PUT": return httpx.Response(504, text="timeout")
        return httpx.Response(200, json=draft)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        client = ZenodoClient("sandbox", "test-token", client=http_client)
        with pytest.raises(zenodo.ZenodoError):
            client.upload_file({"id": 42, "links": {
                "bucket": "https://sandbox.zenodo.org/api/files/verified-bucket"}}, package)
    assert methods == (["PUT", "GET", "GET"] if problem == "missing_file" else ["PUT", "GET"])
    assert pauses == ([0.5] if problem == "missing_file" else [])


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_upload_permanent_failures_are_not_recovered(tmp_path: Path, status: int) -> None:
    package = tmp_path / "support.zip"
    package.write_bytes(b"content")
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(status, text="request rejected")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        client = ZenodoClient("sandbox", "test-token", client=http_client)
        with pytest.raises(zenodo.ZenodoError):
            client.upload_file({"id": 42, "links": {
                "bucket": "https://sandbox.zenodo.org/api/files/verified-bucket"}}, package)
    assert calls == ["PUT"]


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


def test_gateway_delete_recovers_only_the_identified_unpublished_file() -> None:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path))
        assert request.headers["authorization"] == "Bearer test-token"
        if len(calls) == 1:
            return httpx.Response(504)
        if len(calls) == 2:
            return httpx.Response(200, json={"id": 42, "submitted": False,
                "files": [{"id": "file-id", "key": "support file.zip"}]})
        assert calls[-1] == ("DELETE", b"/api/records/42/draft/files/support%20file.zip")
        return httpx.Response(204)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = ZenodoClient("sandbox", "test-token", client=http_client).delete_file(42, "file-id")
    assert result["api"] == "record_draft_files"
    assert result["legacy_status"] == 504
    assert len(calls) == 3


@pytest.mark.parametrize("status", [401, 403, 404])
def test_file_delete_does_not_recover_authorization_or_missing_resource(status: int) -> None:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json={"message": "denied"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(zenodo.ZenodoError, match=f"HTTP {status}"):
            ZenodoClient("sandbox", "test-token", client=http_client).delete_file(42, "file-id")
    assert len(calls) == 1


@pytest.mark.parametrize("draft,reason", [
    ({"id": 43, "submitted": False, "files": []}, "different deposition"),
    ({"id": 42, "submitted": True, "files": []}, "unpublished state"),
    ({"id": 42, "files": []}, "unpublished state"),
    ({"id": 42, "submitted": False, "files": {"enabled": True}}, "uniquely identify"),
    ({"id": 42, "submitted": False, "files": [{"id": "file-id", "key": "a.zip"}, {"id": "file-id", "key": "b.zip"}]}, "uniquely identify"),
    ({"id": 42, "submitted": False, "files": [{"id": "file-id", "key": "../unsafe.zip"}]}, "unsafe filename"),
])
def test_draft_delete_recovery_rejects_unbound_or_unsafe_evidence(draft: dict, reason: str) -> None:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(504) if len(calls) == 1 else httpx.Response(200, json=draft)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(zenodo.ZenodoError, match=reason):
            ZenodoClient("sandbox", "test-token", client=http_client).delete_file(42, "file-id")
    assert len(calls) == 2


def test_gateway_delete_readback_proves_absence_without_deleting_a_replacement() -> None:
    calls = []
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(504) if len(calls) == 1 else httpx.Response(200, json={
            "id": 42, "submitted": False,
            "files": [{"id": "replacement-id", "key": "support.zip"}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        result = ZenodoClient("sandbox", "test-token", client=http_client).delete_file(42, "file-id")
    assert result["already_absent"] is True
    assert len(calls) == 2


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
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("README.md", "new support")
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


def test_explicit_material_release_version_is_independent_of_manuscript() -> None:
    from paper_writing import support

    record = {
        "id": "20260522mathgraph0002", "title": "Versioned materials",
        "version": "1.0.3", "authors": {"names": ["Ada Lovelace"]},
        "support": {"publication": {
            "release_version": "1.0.1", "version": "1.0.0",
            "zenodo": {"version": "1.0.0"},
        }},
    }
    assert zenodo.build_zenodo_metadata(record)["version"] == "1.0.1"
    assert support._record_version(record) == "1.0.1"
    assert record["version"] == "1.0.3"


def test_zenodo_metadata_uses_configured_default_license() -> None:
    record = {
        "id": "20260802mathgraph0001",
        "title": "Licensed support",
        "version": "0.1.3",
        "authors": {"names": ["Ada Lovelace"]},
        "support": {"publication": {"mode": "zenodo_only"}},
    }

    metadata = zenodo.build_zenodo_metadata(
        record,
        default_license="cc-by-4.0",
    )

    assert metadata["license"] == "cc-by-4.0"


def test_zenodo_metadata_preserves_publication_type() -> None:
    record = {
        "id": "20260802mathgraph0001",
        "title": "Versioned manuscript",
        "version": "0.1.3",
        "authors": {"names": ["Ada Lovelace"]},
        "support": {
            "publication": {
                "mode": "zenodo_only",
                "zenodo": {"publication_type": "article"},
            }
        },
    }

    assert zenodo.build_zenodo_metadata(record)["publication_type"] == "article"


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
    paper_id = "20260802mathgraph0001"
    display_id = "20260802-math-graph-opg1757-active-newton"
    evidence = tmp_path / "papers" / paper_id / "evidence"
    evidence.mkdir(parents=True)
    readme = evidence / "REPLAY.md"
    result = evidence / "certificate.json"
    readme.write_text("Run the exact verifier.\n", encoding="utf-8")
    result.write_text('{"verified": true}\n', encoding="utf-8")
    record = {
        "paper_id": paper_id,
        "display_id": display_id,
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
    assert verified["display_id"] == display_id
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
            item["archive_path"].startswith(f"{display_id}-support-v0.1.2/")
            for item in manifest["files"]
        )
        assert any(name.endswith("/SHA256SUMS") for name in archive.namelist())
        release_readme_name = next(
            name for name in archive.namelist() if name.endswith("/ARA_SUPPORT_README.md")
        )
        release_readme = archive.read(release_readme_name).decode("utf-8")
        assert display_id in release_readme
        assert "10.5281/zenodo.123" in release_readme
        assert paper_id not in release_readme
        assert "a" * 40 not in release_readme
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


def test_default_support_archive_uses_display_id_for_legacy_paper_id(tmp_path: Path) -> None:
    record = {
        "paper_id": "20260802mathgraph0001",
        "display_id": "20260802-math-graph-opg1757-deficit-windows",
        "version": "0.1.17",
    }

    path = default_support_archive_path(record, repo_root=tmp_path)

    assert path.name == (
        "20260802-math-graph-opg1757-deficit-windows-support-v0.1.17.zip"
    )


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


def test_production_release_requires_explicit_confirmation(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    """A passing gate alone never authorizes the irreversible external action."""

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
    assert exit_code == 2
    assert "--confirm-production" in output


def test_confirmed_production_release_reaches_quality_gate(
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
            "--confirm-production",
            "--confirm-paper-id",
            paper_id,
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
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
            "--confirm-production",
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


@pytest.mark.parametrize("artifact_backed_package", [False, True])
def test_prepare_and_publish_release_bind_gate_git_and_remote_files(
    tmp_path: Path,
    monkeypatch: Any,
    artifact_backed_package: bool,
) -> None:
    if artifact_backed_package:
        import paper_writing.support as support_module
        monkeypatch.setattr(support_module, "GIT_PAYLOAD_LIMIT_BYTES", 1)
        (tmp_path / ".gitignore").write_text("*.zip\nreference-summary.txt\n", encoding="utf-8")
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
  require_validated_independent_review: false
  maximum_revision_rounds: 3
  conference_minimum_decision: weak_accept
  journal_minimum_decision: minor_revision
defaults: {}
""",
        encoding="utf-8",
    )
    (registry / f"{paper_id}.yaml").write_text(
        f"""paper_id: {paper_id}
display_id: 20260802-math-graph-test-gated-release
created_at: '2026-08-02'
domain: math
subdomain: graph
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
    if artifact_backed_package:
        payload = evidence / "reference-summary.txt"
        payload.write_bytes(b"small unchanged reference summary")
        binding = support_module.write_support_artifact_manifest(
            tmp_path, [payload], f"papers/{paper_id}/artifact-bindings.json"
        )
        record_path = registry / f"{paper_id}.yaml"
        record_path.write_text(record_path.read_text() +
                               f"    artifact_manifests:\n      - {binding.relative_to(tmp_path).as_posix()}\n")
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
    if artifact_backed_package:
        assert len(prepared_record["support"]["publication"]["artifact_manifests"]) == 2
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


@pytest.fixture
def canonical_resume_fixture(tmp_path: Path, monkeypatch: Any) -> dict[str, Any]:
    """Rebuild real Git-frozen sources after a previous partial draft upload."""

    paper_id = "20260802mathgraph0001"
    registry = tmp_path / "registry" / "papers"
    sources = tmp_path / "papers" / paper_id / "evidence" / "release"
    registry.mkdir(parents=True)
    sources.mkdir(parents=True)
    (sources / "REPLAY.md").write_text("Replay this certificate.\n", encoding="utf-8")
    (sources / "certificate.json").write_text('{"ok": true}\n', encoding="utf-8")
    (tmp_path / "registry" / "settings.yaml").write_text(
        "schema_version: ara.paper_writing.registry.v1\ndefaults: {}\n",
        encoding="utf-8",
    )
    record_path = registry / f"{paper_id}.yaml"
    record_path.write_text(
        f"""paper_id: {paper_id}
display_id: 20260802-math-graph-test-resume
domain: math
subdomain: graph
title: Test resumable release
created_at: '2026-08-02'
version: 0.1.2
authors:
  - name: Ada Lovelace
support:
  publication:
    mode: zenodo_only
    status: planned
    source_files:
      - papers/{paper_id}/evidence/release
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "registry", "papers"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=ARA Test", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "freeze support sources"],
        cwd=tmp_path, check=True,
    )
    record = zenodo.find_paper_record(paper_id, repo_root=tmp_path)
    origin_commit = zenodo.git_head(tmp_path)
    previous_package = build_support_archive(
        record, resolve_support_sources(record, repo_root=tmp_path),
        repo_root=tmp_path, reserved_doi="10.5281/zenodo.123",
        origin_commit=origin_commit, license_id="cc-by-4.0",
    )
    paths = [Path(previous_package["archive"]), Path(previous_package["checksum"])]

    def remote_item(path: Path) -> dict[str, Any]:
        return {"id": path.name, "filename": path.name, "filesize": path.stat().st_size,
                "checksum": f"md5:{md5_file(path)}"}

    remote: dict[str, Any] = {
        "id": 123, "submitted": False, "files": [],
        "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.123"}},
    }
    calls: list[tuple[str, Any]] = []
    state: dict[str, Any] = {
        "read_count": 0, "post_build_corruption": None, "final_corruption": None,
    }

    class ResumeClient:
        def __init__(self, environment: str, token: str) -> None:
            assert (environment, token) == ("production", "test-token")

        def __enter__(self) -> "ResumeClient":
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def get_deposition(self, deposition_id: int | str) -> dict[str, Any]:
            assert str(deposition_id) == "123"
            calls.append(("GET", deposition_id))
            state["read_count"] += 1
            result = deepcopy(remote)
            if state["read_count"] == 2 and state["post_build_corruption"]:
                state["post_build_corruption"](result)
            if state["read_count"] == 3 and state["final_corruption"]:
                state["final_corruption"](result)
            return result

        def update_metadata(self, deposition_id: int | str, metadata: dict[str, Any]) -> dict[str, Any]:
            calls.append(("METADATA", deposition_id))
            remote["metadata"].update(metadata)
            remote["metadata"]["prereserve_doi"] = {"doi": "10.5281/zenodo.123"}
            return deepcopy(remote)

        def delete_file(self, deposition_id: int | str, file_id: int | str) -> dict[str, Any]:
            calls.append(("DELETE", file_id))
            remote["files"] = [item for item in remote["files"] if item["id"] != file_id]
            return {"deleted": True}

        def upload_file(self, draft: dict[str, Any], path: str | Path) -> dict[str, Any]:
            assert draft["id"] == 123 and draft["submitted"] is False
            item = remote_item(Path(path))
            calls.append(("PUT", item["filename"]))
            remote["files"].append(item)
            return item

    monkeypatch.setattr(zenodo, "ZenodoClient", ResumeClient)
    return {"paper_id": paper_id, "root": tmp_path, "remote": remote, "calls": calls,
            "paths": paths, "item": remote_item, "previous_package": previous_package,
            "state": state, "record_path": record_path, "client_class": ResumeClient}


@pytest.mark.parametrize("existing", ["empty", "zip", "both", "stale_size", "stale_digest", "unexpected"])
def test_canonical_prepare_resumes_only_missing_or_stale_files(
    canonical_resume_fixture: dict[str, Any], existing: str,
) -> None:
    case = canonical_resume_fixture
    archive, checksum = case["paths"]
    remote = case["remote"]
    item = case["item"]
    if existing != "empty":
        remote["files"] = [item(archive)]
    if existing == "both":
        remote["files"].append(item(checksum))
    elif existing == "stale_size":
        remote["files"][0]["filesize"] += 1
    elif existing == "stale_digest":
        remote["files"][0]["checksum"] = "md5:" + "0" * 32
    elif existing == "unexpected":
        unexpected = item(checksum)
        unexpected.update(id="old-source-id", filename="old.zip")
        remote["files"].append(unexpected)
    prepared = prepare_zenodo_release(
        case["paper_id"], environment="production", token="test-token",
        repo_root=case["root"], deposition_id=123, license_id="cc-by-4.0",
    )
    # This is a genuinely rebuilt canonical package, not a canned mocked ZIP.
    assert prepared["archive_sha256"] == case["previous_package"]["archive_sha256"]
    put_names = [name for method, name in case["calls"] if method == "PUT"]
    deleted = [name for method, name in case["calls"] if method == "DELETE"]
    expected_puts = (
        [] if existing == "both" else [checksum.name] if existing in {"zip", "unexpected"}
        else [archive.name, checksum.name]
    )
    expected_deleted = (
        [archive.name] if existing in {"stale_size", "stale_digest"}
        else ["old-source-id"] if existing == "unexpected" else []
    )
    assert put_names == expected_puts
    assert deleted == expected_deleted
    assert prepared["uploaded_files"] == len(expected_puts)
    assert prepared["removed_draft_files"] == len(expected_deleted)
    assert prepared["reused_files"] == 2 - len(expected_puts)
    receipt = json.loads((case["root"] / prepared["receipt"]).read_text())
    assert len(receipt["reused_remote_files"]) == prepared["reused_files"]
    assert len(receipt["remote_files"]) == 2
    assert receipt["package"]["sha256"] == prepared["archive_sha256"]
    assert receipt["submitted_metadata_sha256"] == receipt["verified_remote_metadata_sha256"]
    # The unchanged verifier still checks both files and the true registry binding.
    verified = verify_prepared_zenodo_draft(
        case["paper_id"], environment="production", token="test-token", repo_root=case["root"],
    )
    assert len(verified["remote_files"]) == 2


@pytest.mark.parametrize("phase", ["initial", "post_build"])
@pytest.mark.parametrize("problem", [
    "wrong_id", "published", "unknown_submission", "missing_inventory", "malformed_entry",
    "missing_name", "inexact_name", "inconsistent_names", "duplicate_name", "duplicate_id",
    "missing_id", "bad_size", "inconsistent_size", "bad_digest",
])
def test_canonical_prepare_rejects_unsafe_inventory_before_file_mutations(
    canonical_resume_fixture: dict[str, Any], phase: str, problem: str,
) -> None:
    case = canonical_resume_fixture
    case["remote"]["files"] = [case["item"](case["paths"][0])]
    original_record = case["record_path"].read_bytes()

    def corrupt(draft: dict[str, Any]) -> None:
        entry = draft["files"][0]
        if problem == "wrong_id":
            draft["id"] = 999
        elif problem == "published":
            draft["submitted"] = True
        elif problem == "unknown_submission":
            draft.pop("submitted")
        elif problem == "missing_inventory":
            draft.pop("files")
        elif problem == "malformed_entry":
            draft["files"].append(None)
        elif problem == "missing_name":
            entry.pop("filename")
        elif problem == "inexact_name":
            entry["filename"] += " "
        elif problem == "inconsistent_names":
            entry["key"] = "different.zip"
        elif problem == "duplicate_name":
            draft["files"].append({**entry, "id": "different-id"})
        elif problem == "duplicate_id":
            draft["files"].append({**entry, "filename": "different.zip"})
        elif problem == "missing_id":
            entry.pop("id")
        elif problem == "bad_size":
            entry["filesize"] = -1
        elif problem == "inconsistent_size":
            entry["size"] = entry["filesize"] + 1
        elif problem == "bad_digest":
            entry["checksum"] = "md5:invalid"
        else:
            raise AssertionError(problem)

    if phase == "initial":
        corrupt(case["remote"])
    else:
        case["state"]["post_build_corruption"] = corrupt
    with pytest.raises(zenodo.ZenodoError):
        prepare_zenodo_release(
            case["paper_id"], environment="production", token="test-token",
            repo_root=case["root"], deposition_id=123, license_id="cc-by-4.0",
        )
    assert not any(method in {"DELETE", "PUT"} for method, _ in case["calls"])
    if phase == "initial":
        assert not any(method == "METADATA" for method, _ in case["calls"])
        assert case["state"]["read_count"] == 1
    else:
        assert case["state"]["read_count"] == 2
        assert [method for method, _ in case["calls"]] == ["GET", "METADATA", "GET"]
    assert case["record_path"].read_bytes() == original_record
    assert not (case["paths"][0].parent / "draft.json").exists()


@pytest.mark.parametrize("problem", ["metadata", "missing_file", "wrong_id", "digest"])
def test_canonical_reuse_still_requires_final_identity_and_both_file_checks(
    canonical_resume_fixture: dict[str, Any], problem: str,
) -> None:
    case = canonical_resume_fixture
    case["remote"]["files"] = [case["item"](path) for path in case["paths"]]
    original_record = case["record_path"].read_bytes()

    def corrupt(draft: dict[str, Any]) -> None:
        if problem == "metadata":
            draft["metadata"]["title"] = "A different release"
        elif problem == "missing_file":
            draft["files"].pop()
        elif problem == "wrong_id":
            draft["id"] = 999
        else:
            draft["files"][0]["checksum"] = "md5:" + "0" * 32

    case["state"]["final_corruption"] = corrupt
    with pytest.raises(zenodo.ZenodoError):
        prepare_zenodo_release(
            case["paper_id"], environment="production", token="test-token",
            repo_root=case["root"], deposition_id=123, license_id="cc-by-4.0",
        )
    assert case["state"]["read_count"] == 3
    assert not any(method in {"DELETE", "PUT"} for method, _ in case["calls"])
    assert case["record_path"].read_bytes() == original_record
    assert not (case["paths"][0].parent / "draft.json").exists()


def test_canonical_prepare_checks_updated_metadata_before_file_mutations(
    canonical_resume_fixture: dict[str, Any],
) -> None:
    case = canonical_resume_fixture
    case["remote"]["files"] = [case["item"](case["paths"][0])]

    def corrupt(draft: dict[str, Any]) -> None:
        draft["metadata"]["title"] = "A different release"

    case["state"]["post_build_corruption"] = corrupt
    with pytest.raises(zenodo.ZenodoError, match="title does not match"):
        prepare_zenodo_release(
            case["paper_id"], environment="production", token="test-token",
            repo_root=case["root"], deposition_id=123, license_id="cc-by-4.0",
        )
    assert case["state"]["read_count"] == 2
    assert not any(method in {"DELETE", "PUT"} for method, _ in case["calls"])
    assert not (case["paths"][0].parent / "draft.json").exists()


def test_canonical_new_version_rejects_metadata_response_from_another_draft(
    canonical_resume_fixture: dict[str, Any], monkeypatch: Any,
) -> None:
    case = canonical_resume_fixture
    record = load_paper_metadata(case["paper_id"], case["root"])
    record["support"]["publication"].update({
        "status": "published",
        "zenodo": {"environment": "production", "deposition_id": 42, "version": "0.1.1"},
    })
    zenodo.write_paper_metadata(case["paper_id"], record, case["root"])
    original_record = case["record_path"].read_bytes()
    client_class = case["client_class"]
    original_update = client_class.update_metadata

    def new_version(self: Any, deposition_id: int | str) -> dict[str, Any]:
        assert deposition_id == 42
        case["calls"].append(("NEW_VERSION", deposition_id))
        return deepcopy(case["remote"])

    def wrong_update(self: Any, deposition_id: int | str, metadata: dict[str, Any]) -> dict[str, Any]:
        assert deposition_id == 123
        response = original_update(self, deposition_id, metadata)
        response["id"] = 999
        return response

    monkeypatch.setattr(client_class, "new_version", new_version, raising=False)
    monkeypatch.setattr(client_class, "update_metadata", wrong_update)
    with pytest.raises(zenodo.ZenodoError, match="metadata update returned a different draft id"):
        prepare_zenodo_release(
            case["paper_id"], environment="production", token="test-token",
            repo_root=case["root"], license_id="cc-by-4.0",
        )
    assert case["calls"] == [("NEW_VERSION", 42), ("METADATA", 123)]
    assert case["record_path"].read_bytes() == original_record
    assert not (case["paths"][0].parent / "draft.json").exists()
