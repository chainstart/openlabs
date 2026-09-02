"""Derived writing-workspace inventory without submission-system state."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from paper_writing.funding import eligible_funding
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
    funding_policies = [
        dict(item) for item in defaults.get("funding", []) if isinstance(item, Mapping)
    ]
    declared_funding = metadata.get("funding")
    funding_source = (
        declared_funding if isinstance(declared_funding, list) else funding_policies
    )
    funding = eligible_funding(funding_source, people, policies=funding_policies)
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


def _research_outcomes(
    metadata: Mapping[str, Any],
    release: Mapping[str, Any],
    publication: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep scientific outcomes separate from the internal writing gate."""

    declared = _mapping(metadata.get("research_outcomes"))
    support_mode = str(publication.get("mode") or "").strip()
    support_status = str(publication.get("status") or "planned").strip()
    reviewed_ready = release.get("status") == "ready"
    support_ready = support_mode == "not_required" or support_status == "published"
    support_policy = _mapping(settings.get("support_publication"))
    auto_release = support_policy.get("release_after_ready") == "automatic"
    return {
        "original_problem_closed": declared.get("original_problem_closed"),
        "new_bound_or_scoped_theorem": declared.get("new_bound_or_scoped_theorem"),
        "writing_package_ready": reviewed_ready,
        "submission_package_ready": reviewed_ready and support_ready,
        "support_auto_release_pending": (
            reviewed_ready and auto_release and support_mode != "not_required" and not support_ready
        ),
        "evidence": _mapping(declared.get("evidence")),
        "scientific_validation": _mapping(metadata.get("scientific_validation")),
    }


def _tri_state_counts(values: list[Any]) -> dict[str, int]:
    return {
        "true": sum(value is True for value in values),
        "false": sum(value is False for value in values),
        "unknown": sum(value is not True and value is not False for value in values),
    }


def build_inventory(
    root: str | Path,
    *,
    config: Mapping[str, Any] | None = None,
    paper_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    settings = dict(config) if config is not None else load_config(repo_root / "registry" / "settings.yaml")
    registry = load_registry(repo_root, paper_ids=paper_ids)
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
        release = _release(metadata)
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
                "writing_release": release,
                "research_outcomes": _research_outcomes(
                    metadata, release, publication, settings
                ),
                "support": support,
                "warnings": paper_warnings,
            }
        )
    releases = Counter(item["writing_release"]["status"] for item in papers)
    original_closure = [
        item["research_outcomes"]["original_problem_closed"] for item in papers
    ]
    scoped_contribution = [
        item["research_outcomes"]["new_bound_or_scoped_theorem"] for item in papers
    ]
    writing_ready = [item["research_outcomes"]["writing_package_ready"] for item in papers]
    submission_ready = [
        item["research_outcomes"]["submission_package_ready"] for item in papers
    ]
    auto_release_pending = [
        item["research_outcomes"]["support_auto_release_pending"] for item in papers
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": ".",
        "summary": {
            "total": len(papers),
            "release_statuses": dict(sorted(releases.items())),
            "research_outcomes": {
                "original_problem_closed": _tri_state_counts(original_closure),
                "new_bound_or_scoped_theorem": _tri_state_counts(scoped_contribution),
                "writing_package_ready": _tri_state_counts(writing_ready),
                "submission_package_ready": _tri_state_counts(submission_ready),
                "support_auto_release_pending": _tri_state_counts(auto_release_pending),
            },
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
