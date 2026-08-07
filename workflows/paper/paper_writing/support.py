"""Deterministic supporting-material archives for Zenodo releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from paper_writing.identifiers import PAPER_ID_PATTERN


SUPPORT_ARCHIVE_SCHEMA_VERSION = "ara.paper_writing.support_archive.v1"
FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_SUPPORT_BYTES = 50_000_000_000
MAX_SUPPORT_FILES = 100_000
EXCLUDED_NAMES = {
    ".DS_Store",
    ".env",
    ".env.local",
    "Thumbs.db",
}
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
}
EXCLUDED_SUFFIXES = {
    ".aux",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".log",
    ".out",
    ".pyc",
    ".synctex.gz",
}


class SupportPackageError(RuntimeError):
    """Raised when a support package cannot be built or verified safely."""


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: str | Path) -> str:
    """Return the MD5 used by Zenodo for transfer-integrity verification.

    MD5 is not used as the repository's release identity; SHA-256 remains the
    canonical package digest.
    """

    digest = hashlib.md5(usedforsecurity=False)
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head(root: str | Path) -> str:
    value = _git_output(Path(root).resolve(), ["rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise SupportPackageError("A support release requires a valid Git HEAD commit")
    return value


def resolve_support_sources(
    record: Mapping[str, Any],
    explicit_sources: Iterable[str | Path] = (),
    *,
    repo_root: str | Path,
) -> list[Path]:
    """Resolve configured files/directories into a safe, sorted file list."""

    root = Path(repo_root).resolve()
    publication = _publication(record)
    configured = publication.get("source_files")
    configured = configured if isinstance(configured, list) else []
    explicit = list(explicit_sources)
    # An explicit public file set is authoritative.  Merging it with the
    # previous release's configured paths silently carries superseded files
    # into a new Zenodo version, which makes the outer version label
    # misleading.  With no explicit set, retain the registry declaration.
    values = explicit if explicit else configured
    if not values:
        raise SupportPackageError(
            "No support source files are declared; set support.publication.source_files "
            "or pass --source"
        )

    resolved: dict[str, Path] = {}
    for value in values:
        unresolved = Path(value)
        if not unresolved.is_absolute():
            unresolved = root / unresolved
        if unresolved.is_symlink():
            raise SupportPackageError(f"Support source symlinks are not allowed: {unresolved}")
        candidate = unresolved.resolve()
        _require_inside_root(candidate, root)
        if candidate.is_dir():
            paths = sorted(candidate.rglob("*"))
        else:
            paths = [candidate]
        for path in paths:
            if path.is_symlink():
                raise SupportPackageError(f"Support source symlinks are not allowed: {path}")
            if not path.is_file():
                if path == candidate:
                    raise SupportPackageError(f"Support source does not exist: {path}")
                continue
            relative = path.relative_to(root).as_posix()
            _validate_source_name(path, relative)
            resolved[relative] = path

    if not resolved:
        raise SupportPackageError("No regular support source files were selected")
    if len(resolved) > MAX_SUPPORT_FILES:
        raise SupportPackageError(
            f"Support package has more than {MAX_SUPPORT_FILES} source files"
        )
    total = sum(path.stat().st_size for path in resolved.values())
    if total > MAX_SUPPORT_BYTES:
        raise SupportPackageError(
            f"Support package sources exceed {MAX_SUPPORT_BYTES} bytes"
        )
    return [resolved[key] for key in sorted(resolved)]


def validate_git_frozen_paths(root: str | Path, paths: Iterable[str | Path]) -> None:
    """Require repository-owned paths to be tracked and unchanged at Git HEAD."""

    repo_root = Path(root).resolve()
    relatives: list[str] = []
    for value in paths:
        path = Path(value).resolve()
        _require_inside_root(path, repo_root)
        if not path.is_file():
            raise SupportPackageError(f"Release file is missing: {path}")
        relatives.append(path.relative_to(repo_root).as_posix())
    relatives = list(dict.fromkeys(relatives))
    if not relatives:
        raise SupportPackageError("No release paths were selected for Git validation")

    tracked_output = _git_output(
        repo_root,
        ["ls-files", "--cached", "-z", "--", *relatives],
    )
    tracked = {item for item in tracked_output.split("\0") if item}
    missing = sorted(set(relatives) - tracked)
    if missing:
        raise SupportPackageError(
            "Support release files are not committed to Git: " + ", ".join(missing[:5])
        )
    status = _git_output(
        repo_root,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", *relatives],
    ).strip()
    if status:
        raise SupportPackageError(
            "Support release files differ from Git HEAD: "
            + "; ".join(status.splitlines()[:5])
        )


def default_support_archive_path(
    record: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> Path:
    paper_id = _paper_id(record)
    version = _safe_component(_record_version(record))
    return (
        Path(repo_root).resolve()
        / "papers"
        / paper_id
        / "support-materials"
        / "zenodo"
        / f"v{version}"
        / f"{paper_id}-support-v{version}.zip"
    )


def build_support_archive(
    record: Mapping[str, Any],
    sources: Iterable[str | Path],
    *,
    repo_root: str | Path,
    output: str | Path | None = None,
    reserved_doi: str | None = None,
    origin_commit: str,
    license_id: str | None = None,
) -> dict[str, Any]:
    """Create a byte-reproducible ZIP, manifest and SHA-256 sidecar."""

    root = Path(repo_root).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", origin_commit):
        raise SupportPackageError("origin_commit must be a full 40-character Git commit")
    paper_id = _paper_id(record)
    version = _record_version(record)
    publication = _publication(record)
    zenodo = publication.get("zenodo")
    zenodo = zenodo if isinstance(zenodo, Mapping) else {}
    declared_license = str(
        license_id or publication.get("license") or zenodo.get("license") or ""
    ).strip()
    if not declared_license:
        raise SupportPackageError(
            "A support-material license is required; set support.publication.license "
            "or pass --license"
        )

    paths = [Path(path).resolve() for path in sources]
    if not paths:
        raise SupportPackageError("No support source files were selected")
    for path in paths:
        _require_inside_root(path, root)
        if not path.is_file():
            raise SupportPackageError(f"Support source does not exist: {path}")

    archive = Path(output).resolve() if output else default_support_archive_path(record, repo_root=root)
    _require_inside_root(archive, root)
    if archive.suffix.casefold() != ".zip":
        raise SupportPackageError("Support archive output must end in .zip")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive_root = f"{paper_id}-support-v{_safe_component(version)}"

    entries: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        archive_relative = _archive_relative_path(path, root, paper_id)
        archive_name = f"{archive_root}/{archive_relative}"
        if archive_name in used_names:
            raise SupportPackageError(f"Duplicate support archive path: {archive_name}")
        used_names.add(archive_name)
        entries.append(
            {
                "archive_path": archive_name,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "path": path,
            }
        )

    readme_name = f"{archive_root}/ARA_SUPPORT_README.md"
    license_name = f"{archive_root}/LICENSE.txt"
    manifest_name = f"{archive_root}/ZENODO_MANIFEST.json"
    sums_name = f"{archive_root}/SHA256SUMS"
    reserved_names = {readme_name, license_name, manifest_name, sums_name}
    collision = next(
        (str(item["archive_path"]) for item in entries if item["archive_path"] in reserved_names),
        None,
    )
    if collision:
        raise SupportPackageError(f"Support source uses a reserved archive path: {collision}")
    generated = {
        readme_name: _support_readme(
            record,
            version=version,
            origin_commit=origin_commit,
            reserved_doi=reserved_doi,
            license_id=declared_license,
        ).encode("utf-8"),
        license_name: _license_declaration(declared_license).encode("utf-8"),
    }
    manifest = {
        "schema_version": SUPPORT_ARCHIVE_SCHEMA_VERSION,
        "paper_id": paper_id,
        "paper_title": str(record.get("title") or paper_id),
        "paper_version": version,
        "origin_repository": "chainstart/ara-paper-writing",
        "origin_commit": origin_commit,
        "reserved_version_doi": reserved_doi,
        "license": declared_license,
        "files": [
            {key: item[key] for key in ("archive_path", "size", "sha256")}
            for item in entries
        ],
    }
    generated[manifest_name] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    checksums = [
        f"{hashlib.sha256(content).hexdigest()}  {name}"
        for name, content in sorted(generated.items())
    ]
    checksums.extend(f"{item['sha256']}  {item['archive_path']}" for item in entries)
    generated[sums_name] = ("\n".join(sorted(checksums)) + "\n").encode("utf-8")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{archive.name}.",
            suffix=".tmp",
            dir=archive.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as output_zip:
            for name, content in sorted(generated.items()):
                _write_zip_bytes(output_zip, name, content)
            for item in sorted(entries, key=lambda value: str(value["archive_path"])):
                _write_zip_file(output_zip, str(item["archive_path"]), Path(item["path"]))
        os.replace(temporary_path, archive)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    archive_sha256 = sha256_file(archive)
    checksum_path = archive.with_suffix(archive.suffix + ".sha256")
    checksum_path.write_text(f"{archive_sha256}  {archive.name}\n", encoding="utf-8")
    return {
        "schema_version": SUPPORT_ARCHIVE_SCHEMA_VERSION,
        "paper_id": paper_id,
        "version": version,
        "origin_commit": origin_commit,
        "reserved_version_doi": reserved_doi,
        "license": declared_license,
        "archive": archive,
        "checksum": checksum_path,
        "archive_sha256": archive_sha256,
        "archive_size": archive.stat().st_size,
        "source_files": [path.relative_to(root).as_posix() for path in paths],
        "file_count": len(entries),
    }


def verify_support_archive(path: str | Path) -> dict[str, Any]:
    """Verify the internal manifest and every SHA-256 entry in an archive."""

    archive = Path(path).resolve()
    if not archive.is_file():
        raise SupportPackageError(f"Support archive is missing: {archive}")
    try:
        return _verify_support_archive_file(archive)
    except SupportPackageError:
        raise
    except (json.JSONDecodeError, KeyError, OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise SupportPackageError(f"Support archive is unreadable or malformed: {archive}") from exc


def _verify_support_archive_file(archive: Path) -> dict[str, Any]:
    with zipfile.ZipFile(archive) as payload:
        names = payload.namelist()
        if len(names) != len(set(names)):
            raise SupportPackageError("Support archive contains duplicate paths")
        for name in names:
            pure = Path(name)
            if pure.is_absolute() or ".." in pure.parts:
                raise SupportPackageError(f"Unsafe support archive path: {name}")
        control_pairs = []
        for name in names:
            if name != "ZENODO_MANIFEST.json" and not name.endswith("/ZENODO_MANIFEST.json"):
                continue
            prefix = name[: -len("ZENODO_MANIFEST.json")]
            sums_name = f"{prefix}SHA256SUMS"
            if sums_name in names:
                control_pairs.append((name, sums_name))
        if control_pairs:
            minimum_depth = min(len(Path(manifest).parts) for manifest, _ in control_pairs)
            control_pairs = [
                pair for pair in control_pairs if len(Path(pair[0]).parts) == minimum_depth
            ]
        if len(control_pairs) != 1:
            raise SupportPackageError("Support archive requires one manifest and one SHA256SUMS")
        manifest_names = [control_pairs[0][0]]
        sums_names = [control_pairs[0][1]]
        manifest = json.loads(payload.read(manifest_names[0]).decode("utf-8"))
        if manifest.get("schema_version") != SUPPORT_ARCHIVE_SCHEMA_VERSION:
            raise SupportPackageError("Unsupported support archive manifest")
        checksum_lines = payload.read(sums_names[0]).decode("utf-8").splitlines()
        expected: dict[str, str] = {}
        for line in checksum_lines:
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                raise SupportPackageError("Malformed support archive SHA256SUMS")
            expected[match.group(2)] = match.group(1)
        actual_files = set(names) - {sums_names[0]}
        if set(expected) != actual_files:
            raise SupportPackageError("Support archive SHA256SUMS does not cover every payload file")
        for name, digest in expected.items():
            if _zip_member_sha256(payload, name) != digest:
                raise SupportPackageError(f"Support archive checksum mismatch: {name}")
        manifest_files = manifest.get("files")
        if not isinstance(manifest_files, list):
            raise SupportPackageError("Support archive manifest is missing its file list")
        for item in manifest_files:
            if not isinstance(item, Mapping):
                raise SupportPackageError("Support archive manifest contains an invalid file entry")
            name = str(item.get("archive_path") or "")
            if name not in names:
                raise SupportPackageError(f"Support archive manifest file is missing: {name}")
            if item.get("size") != payload.getinfo(name).file_size:
                raise SupportPackageError(f"Support archive manifest size mismatch: {name}")
            if item.get("sha256") != _zip_member_sha256(payload, name):
                raise SupportPackageError(f"Support archive manifest checksum mismatch: {name}")
    return {
        "schema_version": manifest["schema_version"],
        "paper_id": manifest.get("paper_id"),
        "paper_version": manifest.get("paper_version"),
        "origin_commit": manifest.get("origin_commit"),
        "reserved_version_doi": manifest.get("reserved_version_doi"),
        "license": manifest.get("license"),
        "archive_sha256": sha256_file(archive),
        "archive_size": archive.stat().st_size,
        "files": manifest.get("files", []),
    }


def _paper_id(record: Mapping[str, Any]) -> str:
    value = str(record.get("id") or record.get("paper_id") or "").strip()
    if not PAPER_ID_PATTERN.fullmatch(value):
        raise SupportPackageError(f"Invalid paper_id for support release: {value!r}")
    return value


def _record_version(record: Mapping[str, Any]) -> str:
    direct = record.get("version")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    metadata = record.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    manuscript = record.get("manuscript")
    if isinstance(manuscript, Mapping):
        version = manuscript.get("version")
        if isinstance(version, Mapping):
            value = version.get("label")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "1.0.0"


def _publication(record: Mapping[str, Any]) -> Mapping[str, Any]:
    support = record.get("support")
    support = support if isinstance(support, Mapping) else {}
    publication = support.get("publication")
    return publication if isinstance(publication, Mapping) else {}


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or "1.0.0"


def _archive_relative_path(path: Path, root: Path, paper_id: str) -> str:
    relative = path.relative_to(root)
    workspace = Path("papers") / paper_id
    try:
        return relative.relative_to(workspace).as_posix()
    except ValueError:
        return (Path("repository") / relative).as_posix()


def _validate_source_name(path: Path, relative: str) -> None:
    relative_parts = Path(relative).parts
    if any(
        relative_parts[index : index + 2] == ("support-materials", "zenodo")
        for index in range(max(0, len(relative_parts) - 1))
    ):
        raise SupportPackageError(f"Generated Zenodo output cannot be a support source: {relative}")
    if path.name in EXCLUDED_NAMES or any(part in EXCLUDED_PARTS for part in path.parts):
        raise SupportPackageError(f"Excluded support source path: {relative}")
    folded = path.name.casefold()
    if folded.startswith(".env") or folded in {"id_dsa", "id_ed25519", "id_rsa"}:
        raise SupportPackageError(f"Potential credential file cannot be packaged: {relative}")
    if path.suffix.casefold() in {".key", ".p12", ".pem", ".pfx"}:
        raise SupportPackageError(f"Potential credential file cannot be packaged: {relative}")
    if any(folded.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
        raise SupportPackageError(f"Generated/cache file cannot be support material: {relative}")
    if any(token in folded for token in ("access_token", "api_key", "credentials", "secret.key")):
        raise SupportPackageError(f"Potential credential file cannot be packaged: {relative}")


def _require_inside_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SupportPackageError(f"Support release path must stay inside the repository: {path}") from exc


def _support_readme(
    record: Mapping[str, Any],
    *,
    version: str,
    origin_commit: str,
    reserved_doi: str | None,
    license_id: str,
) -> str:
    doi_line = reserved_doi or "not reserved when this archive was built"
    return (
        "# ARA supporting-material release\n\n"
        f"- Paper ID: `{_paper_id(record)}`\n"
        f"- Paper title: {record.get('title') or _paper_id(record)}\n"
        f"- Paper version: `{version}`\n"
        f"- Writing source commit: `{origin_commit}`\n"
        f"- Zenodo Version DOI: `{doi_line}`\n"
        f"- Declared license: `{license_id}`\n\n"
        "`ZENODO_MANIFEST.json` records the archive-relative path, byte size and SHA-256 "
        "of each selected source file. `SHA256SUMS` covers every other file in this archive.\n"
    )


def _license_declaration(license_id: str) -> str:
    return (
        f"Declared license identifier: {license_id}\n\n"
        "This identifier is supplied by the paper registry. Review the selected license and "
        "all third-party file rights before publication. Component files with their own "
        "license notices retain those notices.\n"
    )


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def _write_zip_bytes(output: zipfile.ZipFile, name: str, content: bytes) -> None:
    output.writestr(_zip_info(name), content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _write_zip_file(output: zipfile.ZipFile, name: str, path: Path) -> None:
    with path.open("rb") as source, output.open(_zip_info(name), "w", force_zip64=True) as target:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            target.write(block)


def _zip_member_sha256(payload: zipfile.ZipFile, name: str) -> str:
    digest = hashlib.sha256()
    with payload.open(name) as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_output(root: Path, arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise SupportPackageError("Git is required for a support release") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise SupportPackageError(detail)
    return result.stdout
