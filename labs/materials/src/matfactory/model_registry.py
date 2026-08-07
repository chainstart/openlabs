"""Freeze open atomistic model files before any screening calculation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .provenance import (
    atomic_write_json,
    environment_versions,
    fingerprint,
    sha256_file,
)

_ROOT = Path(__file__).resolve().parents[2]
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class ModelSource:
    model_id: str
    family: str
    package: str
    expected_package_version: str
    source_type: str
    source: str
    filename: str
    license_id: str
    training_lineage: str
    intended_use: str


@dataclass(frozen=True)
class ModelRegistryProtocol:
    registry_id: str
    protocol_path: Path
    protocol_sha256: str
    root_dir: Path
    models: tuple[ModelSource, ...]


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (_ROOT / path).resolve()


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def load_model_registry_protocol(path: Path | str) -> ModelRegistryProtocol:
    """Validate model sources without importing either model implementation."""
    protocol_path = Path(path).resolve()
    payload = _read_json(protocol_path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("model registry schema_version must be '1.0'")
    registry_id = payload.get("registry_id")
    if not isinstance(registry_id, str) or not _SAFE_ID.fullmatch(registry_id):
        raise ValueError("registry_id must be a safe lowercase identifier")
    model_rows = payload.get("models")
    if not isinstance(model_rows, list) or len(model_rows) < 2:
        raise ValueError("at least two model sources are required")
    models: list[ModelSource] = []
    seen: set[str] = set()
    families: set[str] = set()
    for row in model_rows:
        if not isinstance(row, dict):
            raise TypeError("each model source must be an object")
        required = (
            "model_id",
            "family",
            "package",
            "expected_package_version",
            "source_type",
            "source",
            "filename",
            "license_id",
            "training_lineage",
            "intended_use",
        )
        if any(not isinstance(row.get(key), str) or not row[key] for key in required):
            raise ValueError("model source fields must be non-empty strings")
        model_id = str(row["model_id"])
        if not _SAFE_ID.fullmatch(model_id) or model_id in seen:
            raise ValueError(f"unsafe or duplicate model_id {model_id!r}")
        seen.add(model_id)
        family = str(row["family"])
        families.add(family)
        source_type = str(row["source_type"])
        if source_type not in {"https", "python-package", "local-file"}:
            raise ValueError(f"unsupported source_type {source_type!r}")
        source = str(row["source"])
        if source_type == "https" and urlparse(source).scheme != "https":
            raise ValueError("remote model sources must use HTTPS")
        filename = str(row["filename"])
        if Path(filename).name != filename:
            raise ValueError("model filename must not contain directories")
        models.append(
            ModelSource(
                model_id=model_id,
                family=family,
                package=str(row["package"]),
                expected_package_version=str(row["expected_package_version"]),
                source_type=source_type,
                source=source,
                filename=filename,
                license_id=str(row["license_id"]),
                training_lineage=str(row["training_lineage"]),
                intended_use=str(row["intended_use"]),
            )
        )
    if len(families) < 2:
        raise ValueError("registry must contain at least two model families")
    return ModelRegistryProtocol(
        registry_id=registry_id,
        protocol_path=protocol_path,
        protocol_sha256=sha256_file(protocol_path),
        root_dir=_repo_path(
            str(payload.get("root_dir", f"cache/models/{registry_id}"))
        ),
        models=tuple(models),
    )


def _source_path(model: ModelSource) -> Path | None:
    if model.source_type == "local-file":
        return _repo_path(model.source)
    if model.source_type == "python-package":
        package_name, separator, relative = model.source.partition(":")
        if not separator or not package_name or not relative:
            raise ValueError(
                "python-package source must be 'import_package:relative/path'"
            )
        resource = resources.files(package_name).joinpath(relative)
        if not resource.is_file():
            raise FileNotFoundError(f"package model artifact not found: {model.source}")
        return Path(str(resource)).resolve()
    return None


def _download(url: str, target: Path, user_agent: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(request, timeout=180.0) as response:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _materialize(model: ModelSource, root_dir: Path) -> Path:
    try:
        observed_version = version(model.package)
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"required package is not installed: {model.package}"
        ) from exc
    if observed_version != model.expected_package_version:
        raise RuntimeError(
            f"{model.package} version changed: expected "
            f"{model.expected_package_version}, got {observed_version}"
        )
    target = root_dir / model.filename
    if target.is_file():
        return target
    source_path = _source_path(model)
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path is not None:
        shutil.copyfile(source_path, target)
    else:
        _download(
            model.source,
            target,
            "matfactory/0.2 model-registry (open materials research)",
        )
    return target


def _verify_existing(
    protocol: ModelRegistryProtocol, manifest: dict[str, Any]
) -> dict[str, Any]:
    if manifest.get("protocol_sha256") != protocol.protocol_sha256:
        raise RuntimeError("model registry protocol changed; use a new registry_id")
    records = manifest.get("models")
    if not isinstance(records, list) or len(records) != len(protocol.models):
        raise RuntimeError("frozen model registry is incomplete")
    for record in records:
        path = Path(str(record.get("artifact_path", "")))
        if not path.is_file() or sha256_file(path) != record.get("artifact_sha256"):
            raise RuntimeError(f"frozen model artifact changed or vanished: {path}")
    expected_content = _content_fingerprint(protocol, records)
    if manifest.get("content_fingerprint") not in {None, expected_content}:
        raise RuntimeError("frozen model registry content fingerprint changed")
    if manifest.get("content_fingerprint") is None:
        manifest["content_fingerprint"] = expected_content
        manifest["manifest_fingerprint"] = fingerprint(
            {
                key: value
                for key, value in manifest.items()
                if key != "manifest_fingerprint"
            }
        )
        atomic_write_json(protocol.root_dir / "model-registry.json", manifest)
    return manifest


def _content_fingerprint(
    protocol: ModelRegistryProtocol, records: list[dict[str, Any]]
) -> str:
    stable_records = [
        {
            key: record[key]
            for key in (
                "model_id",
                "family",
                "package",
                "package_version",
                "source_type",
                "source",
                "license_id",
                "training_lineage",
                "intended_use",
                "artifact_sha256",
                "artifact_bytes",
            )
        }
        for record in records
    ]
    return fingerprint(
        {
            "registry_id": protocol.registry_id,
            "protocol_sha256": protocol.protocol_sha256,
            "models": stable_records,
        }
    )


def freeze_model_registry(path: Path | str) -> dict[str, Any]:
    """Download/copy each model exactly once and record content hashes."""
    protocol = load_model_registry_protocol(path)
    manifest_path = protocol.root_dir / "model-registry.json"
    if manifest_path.is_file():
        return _verify_existing(protocol, _read_json(manifest_path))
    records: list[dict[str, Any]] = []
    for model in protocol.models:
        artifact = _materialize(model, protocol.root_dir)
        records.append(
            {
                "model_id": model.model_id,
                "family": model.family,
                "package": model.package,
                "package_version": model.expected_package_version,
                "source_type": model.source_type,
                "source": model.source,
                "license_id": model.license_id,
                "training_lineage": model.training_lineage,
                "intended_use": model.intended_use,
                "artifact_path": str(artifact.resolve()),
                "artifact_sha256": sha256_file(artifact),
                "artifact_bytes": artifact.stat().st_size,
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "manifest_kind": "frozen-open-model-registry",
        "registry_id": protocol.registry_id,
        "created_unix_time": time.time(),
        "protocol_path": str(protocol.protocol_path),
        "protocol_sha256": protocol.protocol_sha256,
        "environment": environment_versions(
            ("chgnet", "mace-torch", "torch", "ase", "pymatgen")
        ),
        "models": records,
        "scientific_boundary": (
            "Both models inherit Materials Project trajectory data. Agreement is "
            "an architecture-level screen, not independent validation; DFT is required."
        ),
    }
    manifest["content_fingerprint"] = _content_fingerprint(protocol, records)
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol")
    args = parser.parse_args()
    print(json.dumps(freeze_model_registry(args.protocol), indent=2))


if __name__ == "__main__":
    main()
