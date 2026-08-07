"""Derived writing-workspace inventory without submission-system state."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from paper_writing.identifiers import PAPER_ID_PATTERN
from paper_writing.registry import load_registry, repository_root


SCHEMA_VERSION = "openlabs.paper_writing.inventory.v1"


def default_repo_root() -> Path:
    return repository_root()


def default_config_path() -> Path:
    return default_repo_root() / "registry" / "settings.yaml"


def default_output_path() -> Path:
    return default_repo_root() / "ledger" / "paper-inventory.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path or default_config_path()).resolve()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"settings root must be an object: {config_path}")
    return payload


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _authors(metadata: Mapping[str, Any], settings: Mapping[str, Any]) -> dict[str, Any]:
    explicit = metadata.get("authors")
    if isinstance(explicit, list):
        people = [dict(item) for item in explicit if isinstance(item, Mapping)]
    elif isinstance(explicit, Mapping):
        people = [
            dict(item)
            for item in explicit.get("people", [])
            if isinstance(item, Mapping)
        ]
    else:
        people = []
    defaults = _mapping(settings.get("defaults"))
    effective_from = str(defaults.get("authors_effective_from") or "")
    created_at = str(metadata.get("created_at") or "")
    if not people and (not effective_from or created_at >= effective_from):
        people = [
            dict(item)
            for item in defaults.get("authors", [])
            if isinstance(item, Mapping)
        ]
    affiliations = [
        dict(item)
        for item in defaults.get("affiliations", [])
        if isinstance(item, Mapping)
    ]
    funding = [
        dict(item)
        for item in defaults.get("funding", [])
        if isinstance(item, Mapping)
    ]
    return {
        "names": [str(item.get("name")) for item in people if item.get("name")],
        "people": people,
        "affiliations": affiliations,
        "funding": funding,
    }


def _release(metadata: Mapping[str, Any]) -> dict[str, Any]:
    release = _mapping(metadata.get("writing_release"))
    if release:
        return release
    return {
        "status": "draft",
        "source": "registry_default",
        "score": None,
        "decision": None,
        "reviewed_at": None,
    }


def build_inventory(
    root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    settings = dict(config) if config is not None else load_config(repo_root / "registry" / "settings.yaml")
    registry = load_registry(repo_root)
    papers: list[dict[str, Any]] = []
    warnings: list[str] = []
    for workspace, metadata_value in sorted(registry.get("papers", {}).items()):
        metadata = _mapping(metadata_value)
        paper_id = str(metadata.get("paper_id") or "")
        manuscript_dir = repo_root / str(metadata.get("manuscript_dir") or f"{workspace}/manuscript")
        source = manuscript_dir / "main.tex"
        pdf = manuscript_dir / "main.pdf"
        claim_map = repo_root / workspace / "evidence" / "claim_evidence_map.md"
        paper_warnings = []
        if not source.is_file():
            paper_warnings.append("canonical LaTeX source is missing")
        if not pdf.is_file():
            paper_warnings.append("compiled PDF is missing")
        if not claim_map.is_file():
            paper_warnings.append("claim-evidence map is missing")
        for warning in paper_warnings:
            warnings.append(f"{paper_id}: {warning}")
        support = _mapping(metadata.get("support"))
        publication = _mapping(support.get("publication"))
        support["publication"] = publication
        papers.append(
            {
                "id": paper_id,
                "title": str(metadata.get("title") or paper_id),
                "root_path": workspace,
                "metadata": metadata,
                "manuscript": {
                    "directory": manuscript_dir.relative_to(repo_root).as_posix(),
                    "source": source.relative_to(repo_root).as_posix() if source.is_file() else None,
                    "pdf": pdf.relative_to(repo_root).as_posix() if pdf.is_file() else None,
                    "version": {"label": str(metadata.get("version") or "0.1.0")},
                },
                "authors": _authors(metadata, settings),
                "writing_release": _release(metadata),
                "support": support,
                "warnings": paper_warnings,
            }
        )
    releases = Counter(item["writing_release"]["status"] for item in papers)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": ".",
        "summary": {
            "total": len(papers),
            "release_statuses": dict(sorted(releases.items())),
            "needs_attention": sum(bool(item["warnings"]) for item in papers),
        },
        "papers": papers,
        "warnings": warnings,
    }


def write_inventory(payload: Mapping[str, Any], output: str | Path) -> Path:
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
