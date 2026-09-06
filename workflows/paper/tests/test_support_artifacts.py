import json
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import paper_writing.support as support


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=Artifact Test", "-c",
                           "user.email=artifact@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout


def commit(root, *paths):
    git(root, "add", "--", *map(str, paths))
    git(root, "commit", "-qm", "freeze artifact binding")


@pytest.fixture
def bound(tmp_path):
    root = tmp_path / "openlabs-data"
    root.mkdir()
    git(root, "init", "-q")
    (root / ".gitignore").write_text("*.npz\n*.zip\n")
    commit(root, ".gitignore")
    cache = root / "papers/example/public-support-v1.0.0/full.npz"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"complete numerical payload")
    manifest = support.write_support_artifact_manifest(root, [cache], "bindings.json")
    item = json.loads(manifest.read_text())["files"][0]
    artifact = Path(unquote(urlparse(item["artifact_uri"]).path))
    return root, cache, manifest, artifact


def test_explicit_committed_manifest_freezes_both_complete_copies(bound):
    root, cache, manifest, artifact = bound
    commit(root, manifest)
    support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])
    assert cache.read_bytes() == artifact.read_bytes()
    assert not git(root, "ls-files", "--", str(cache)).strip()
    assert git(root, "check-ignore", str(cache)).strip()
    with pytest.raises(support.SupportPackageError, match="not committed"):
        support.validate_git_frozen_paths(root, [cache])


@pytest.mark.parametrize("state", ["untracked", "staged", "dirty", "missing"])
def test_manifest_must_be_frozen_at_head(bound, state):
    root, cache, manifest, _ = bound
    if state == "staged":
        git(root, "add", str(manifest))
    elif state in {"dirty", "missing"}:
        commit(root, manifest)
        if state == "dirty":
            manifest.write_text(manifest.read_text() + "\n")
        else:
            manifest.unlink()
    with pytest.raises(support.SupportPackageError):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


@pytest.mark.parametrize("which,operation", [("cache", "tamper"), ("artifact", "tamper"),
                                           ("cache", "missing"), ("artifact", "missing")])
def test_missing_or_same_size_tampered_payloads_fail(bound, which, operation):
    root, cache, manifest, artifact = bound
    commit(root, manifest)
    selected = cache if which == "cache" else artifact
    if operation == "missing":
        selected.unlink()
    else:
        selected.write_bytes(b"x" * selected.stat().st_size)
    with pytest.raises(support.SupportPackageError):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


@pytest.mark.parametrize("attack", ["duplicate", "traversal", "absolute", "noncanonical", "badsize",
                                   "boolsize", "badhash", "http", "floating", "query", "outside",
                                   "schema", "empty", "malformed"])
def test_committed_malicious_manifests_do_not_authorize_payloads(bound, attack):
    root, cache, manifest, artifact = bound
    doc = json.loads(manifest.read_text())
    row = doc["files"][0]
    if attack == "duplicate":
        doc["files"].append(dict(row))
    elif attack == "traversal":
        row["path"] = "../outside.npz"
    elif attack == "absolute":
        row["path"] = str(cache)
    elif attack == "noncanonical":
        row["path"] = "./" + row["path"]
    elif attack == "badsize":
        row["size"] = -1
    elif attack == "boolsize":
        row["size"] = True
    elif attack == "badhash":
        row["sha256"] = "a" * 63
    elif attack == "http":
        row["artifact_uri"] = "https://example.invalid/bytes"
    elif attack == "floating":
        row["artifact_uri"] = (root.parent / "openlabs-artifacts/latest.npz").as_uri()
    elif attack == "query":
        row["artifact_uri"] += "?mutable=true"
    elif attack == "outside":
        row["artifact_uri"] = (root.parent / "outside" / row["sha256"] / "full.npz").as_uri()
    elif attack == "schema":
        doc["schema_version"] = "unknown"
    elif attack == "empty":
        doc["files"] = []
    manifest.write_text("{" if attack == "malformed" else json.dumps(doc))
    commit(root, manifest)
    with pytest.raises(support.SupportPackageError):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


@pytest.mark.parametrize("which", ["cache", "cache-parent", "artifact", "artifact-parent", "manifest"])
def test_symlinks_cannot_redirect_frozen_bindings(bound, which):
    root, cache, manifest, artifact = bound
    commit(root, manifest)
    selected = {"cache": cache, "cache-parent": cache.parent, "artifact": artifact,
                "artifact-parent": artifact.parent, "manifest": manifest}[which]
    moved = selected.with_name(selected.name + ".original")
    selected.rename(moved)
    selected.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(support.SupportPackageError, match="symlink|Git HEAD"):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


def test_duplicate_manifest_and_unbound_extra_file_fail(bound):
    root, cache, manifest, _ = bound
    commit(root, manifest)
    with pytest.raises(support.SupportPackageError, match="Duplicate"):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest, manifest])
    extra = cache.with_name("extra.npz")
    extra.write_bytes(b"not bound")
    with pytest.raises(support.SupportPackageError, match="not committed"):
        support.validate_git_frozen_paths(root, [cache, extra], artifact_manifests=[manifest])


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_index_status_hints_cannot_hide_modified_manifest_bytes(bound, flag):
    root, cache, manifest, _ = bound
    commit(root, manifest)
    git(root, "update-index", flag, str(manifest))
    manifest.write_text(manifest.read_text() + "\n")
    with pytest.raises(support.SupportPackageError, match="Git HEAD"):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


def test_manifest_cannot_launder_dirty_tracked_source(bound):
    root, cache, manifest, _ = bound
    git(root, "add", "-f", str(cache))
    commit(root, manifest)
    cache.write_bytes(b"new uncommitted scientific bytes")
    support.write_support_artifact_manifest(root, [cache], manifest)
    commit(root, manifest)
    with pytest.raises(support.SupportPackageError, match="Git HEAD"):
        support.validate_git_frozen_paths(root, [cache], artifact_manifests=[manifest])


def test_snapshot_still_hashes_full_payload_and_checks_authoritative_copy(bound):
    root, cache, manifest, artifact = bound
    record = {"support": {"publication": {"source_files": [str(cache.relative_to(root))],
                                           "artifact_manifests": [str(manifest.relative_to(root))]}}}
    snapshot = support.support_sources_snapshot_sha256(record, repo_root=root)
    ordinary = {"support": {"publication": {"source_files": [str(cache.relative_to(root))]}}}
    assert snapshot == support.support_sources_snapshot_sha256(ordinary, repo_root=root)
    artifact.write_bytes(b"x" * artifact.stat().st_size)
    with pytest.raises(support.SupportPackageError, match="authoritative artifact"):
        support.support_sources_snapshot_sha256(record, repo_root=root)


def test_large_generated_zip_uses_artifact_binding_but_contains_full_payload(bound, monkeypatch):
    root, cache, source_manifest, _ = bound
    commit(root, source_manifest)
    monkeypatch.setattr(support, "GIT_PAYLOAD_LIMIT_BYTES", 1)
    record = {"paper_id": "20260906-physics-test-artifact-support", "version": "1.0.0",
              "title": "Test", "support": {"publication": {"license": "cc-by-4.0"}}}
    package = support.build_support_archive(record, [cache], repo_root=root, origin_commit=support.git_head(root))
    assert package["artifact_manifest"].is_file()
    commit(root, package["artifact_manifest"], package["checksum"])
    support.validate_git_frozen_paths(root, [cache, package["archive"], package["checksum"]],
                                     artifact_manifests=[source_manifest, package["artifact_manifest"]])
    verified = support.verify_support_archive(package["archive"])
    with zipfile.ZipFile(package["archive"]) as archive:
        entry = verified["files"][0]
        assert archive.read(entry["archive_path"]) == cache.read_bytes()
    doc = json.loads(package["artifact_manifest"].read_text())
    original = Path(unquote(urlparse(doc["files"][0]["artifact_uri"]).path))
    assert support.sha256_file(original) == package["archive_sha256"]
    original.write_bytes(b"bad" * 10)
    with pytest.raises(support.SupportPackageError, match="authoritative artifact"):
        support.validate_git_frozen_paths(root, [package["archive"]], artifact_manifests=[package["artifact_manifest"]])


def test_small_archive_keeps_original_git_path_contract(bound):
    root, cache, _, _ = bound
    record = {"paper_id": "20260906-physics-test-artifact-support", "version": "1.0.0",
              "title": "Test", "support": {"publication": {"license": "cc-by-4.0"}}}
    package = support.build_support_archive(record, [cache], repo_root=root, origin_commit=support.git_head(root))
    assert package["artifact_manifest"] is None
