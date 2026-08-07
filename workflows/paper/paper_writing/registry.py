"""Load the repository-wide settings and one-YAML-per-paper registry."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import yaml

from paper_writing.identifiers import (
    PAPER_ID_PATTERN,
    WORK_ID_PATTERN,
    domain_scoped_parts,
    work_id_from_paper_id,
)


REGISTRY_SCHEMA_VERSION = "ara.paper_writing.registry.v1"


def repository_root() -> Path:
    configured_data = os.environ.get("OPENLABS_DATA")
    if configured_data:
        return Path(configured_data).expanduser().resolve()
    configured_workspace = os.environ.get("OPENLABS_WORKSPACE")
    if configured_workspace:
        return (Path(configured_workspace).expanduser().resolve() / "data").resolve()
    source = Path(__file__).resolve()
    for parent in source.parents:
        if (parent / "openlabs" / "config" / "openlabs.toml").is_file():
            return (parent / "data").resolve()
    # Compatibility fallback for an independently installed legacy workspace.
    return source.parents[1]


def settings_path(root: str | Path | None = None) -> Path:
    return Path(root or repository_root()).resolve() / "registry" / "settings.yaml"


def paper_metadata_path(paper_id: str, root: str | Path | None = None) -> Path:
    return Path(root or repository_root()).resolve() / "registry" / "papers" / f"{paper_id}.yaml"


def _load_yaml(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be an object: {path}")
    return payload


def load_registry(
    root: str | Path | None = None,
    *,
    settings: str | Path | None = None,
    include_local_repositories: bool = True,
) -> dict[str, Any]:
    """Return the compatibility config consumed by the inventory scanner.

    The public registry is split across small YAML files. This function projects it into the
    historical ``papers`` mapping so the proven inventory scanner can remain focused on file
    discovery and derived status calculations.
    """

    repo_root = Path(root or repository_root()).resolve()
    global_settings = _load_yaml(Path(settings).resolve() if settings else settings_path(repo_root))
    schema_version = global_settings.get("schema_version")
    if schema_version != REGISTRY_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported registry schema {schema_version!r}; expected {REGISTRY_SCHEMA_VERSION!r}"
        )

    config = deepcopy(global_settings)
    config["papers"] = {}
    paper_dir = repo_root / "registry" / "papers"
    for path in sorted(paper_dir.glob("*.yaml")):
        paper = _load_yaml(path)
        paper_id = str(paper.get("paper_id") or "").strip()
        if not paper_id:
            raise ValueError(f"paper_id is required: {path}")
        if not PAPER_ID_PATTERN.fullmatch(paper_id):
            raise ValueError(f"paper_id has an unsupported format: {paper_id!r}")
        if paper_id != path.stem:
            raise ValueError(f"paper_id {paper_id!r} must match registry filename {path.stem!r}")
        derived_work_id = work_id_from_paper_id(paper_id)
        canonical_parts = domain_scoped_parts(paper_id)
        domain = str(paper.get("domain") or "").strip()
        subdomain = str(paper.get("subdomain") or "").strip()
        if canonical_parts and (
            canonical_parts["domain"] != domain
            or canonical_parts["subdomain"] != subdomain
        ):
            raise ValueError(
                f"paper_id domain/subdomain segments must match registry metadata for {paper_id}"
            )
        work_id = str(paper.get("work_id") or derived_work_id or "").strip()
        if work_id and not WORK_ID_PATTERN.fullmatch(work_id):
            raise ValueError(f"work_id has an unsupported format for {paper_id}: {work_id!r}")
        if derived_work_id and work_id != derived_work_id:
            raise ValueError(
                f"work_id {work_id!r} must match the descriptive paper_id suffix "
                f"{derived_work_id!r}"
            )
        if work_id:
            paper["work_id"] = work_id
        display_id = str(
            paper.get("display_id") or (paper_id if canonical_parts else "")
        ).strip()
        if display_id:
            display_parts = domain_scoped_parts(display_id)
            if not display_parts:
                raise ValueError(
                    f"display_id must use YYYYMMDD-domain-subdomain-keywords for {paper_id}"
                )
            expected_date = str(paper.get("created_at") or "").replace("-", "")
            if display_parts["date"] != expected_date:
                raise ValueError(f"display_id date must match created_at for {paper_id}")
            if (
                display_parts["domain"] != domain
                or display_parts["subdomain"] != subdomain
            ):
                raise ValueError(
                    f"display_id domain/subdomain must match registry metadata for {paper_id}"
                )
            paper["display_id"] = display_id
        target_journal = paper.get("target_journal")
        if target_journal is not None:
            if not isinstance(target_journal, str) or not target_journal.strip():
                raise ValueError(f"target_journal must be a non-empty string for {paper_id}")
            if len(target_journal.strip()) > 500:
                raise ValueError(f"target_journal is too long for {paper_id}")
            paper["target_journal"] = target_journal.strip()
        workspace = str(paper.pop("workspace", f"papers/{paper_id}")).strip("/")
        paper.setdefault("manuscript_dir", f"{workspace}/manuscript")
        source = repo_root / paper["manuscript_dir"] / "main.tex"
        pdf = repo_root / paper["manuscript_dir"] / "main.pdf"
        if source.exists():
            paper.setdefault("latest_source", source.relative_to(repo_root).as_posix())
        if pdf.exists():
            paper.setdefault("latest_pdf", pdf.relative_to(repo_root).as_posix())
        paper.setdefault("record_status", "final_manuscript")
        paper.setdefault("title_history", [])
        paper.setdefault("evidence_bundles", [])
        paper.setdefault("metadata_file", path.relative_to(repo_root).as_posix())
        config["papers"][workspace] = paper

    if include_local_repositories:
        local = _load_yaml(repo_root / "registry" / "repositories.local.yaml", required=False)
        repositories = local.get("repositories", {})
        if repositories and not isinstance(repositories, Mapping):
            raise ValueError("registry/repositories.local.yaml repositories must be an object")
        config["evidence_repositories"] = {
            str(name): str(location) for name, location in repositories.items()
        }
    else:
        config["evidence_repositories"] = {}
    return config


def load_paper_metadata(paper_id: str, root: str | Path | None = None) -> dict[str, Any]:
    return _load_yaml(paper_metadata_path(paper_id, root))


def write_paper_metadata(
    paper_id: str,
    payload: Mapping[str, Any],
    root: str | Path | None = None,
) -> Path:
    path = paper_metadata_path(paper_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["paper_id"] = paper_id
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000),
        encoding="utf-8",
    )
    return path
