#!/usr/bin/env python3
"""Refresh the small OpenLabs query index from durable file-owned state."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "orchestrator" / "src"))
sys.path.insert(0, str(CODE_ROOT / "workflows" / "paper"))

from openlabs.config import workspace_paths
from openlabs.contracts import atomic_write_json
from openlabs.db import FactoryDB
from paper_writing.registry import load_registry


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_state(path: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status_output = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    diff_stat = subprocess.run(
        ["git", "-C", str(path), "diff", "--stat", "--no-ext-diff"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "path": str(path),
        "commit": commit,
        "dirty_entries": len(status_output.splitlines()),
        "status_sha256": hashlib.sha256(status_output.encode("utf-8")).hexdigest(),
        "tracked_diff_stat_sha256": hashlib.sha256(
            diff_stat.encode("utf-8")
        ).hexdigest(),
    }


def _count_files(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file()) if root.is_dir() else 0


def _index_math(db: FactoryDB, data: Path) -> tuple[int, int]:
    states: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted((data / "workspaces" / "math").glob("*/campaign_state.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            states.append((path, payload))

    latest_problem: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, payload in states:
        campaign_id = str(payload.get("campaign_id") or path.parent.name)
        phase = str(payload.get("phase") or "unknown")
        title = str(payload.get("title") or campaign_id)
        relative = path.relative_to(data).as_posix()
        status = "frozen" if phase == "frozen" else "active"
        db.register_campaign(
            campaign_id,
            domain="math",
            title=title,
            status=status,
            state_path=path.parent.relative_to(data).as_posix(),
            source="amra-research-loop",
        )
        db.upsert_research_record(
            f"campaign:{campaign_id}",
            kind="campaign",
            domain="math",
            title=title,
            status=status,
            source_path=relative,
            metadata={"phase": phase, "problem_id": payload.get("problem_id")},
        )
        problem_id = str(payload.get("problem_id") or "").strip()
        problem_key = problem_id.lower()
        if problem_key:
            previous = latest_problem.get(problem_key)
            if previous is None or str(payload.get("updated_at") or "") > str(
                previous[1].get("updated_at") or ""
            ):
                latest_problem[problem_key] = (path, payload)

    for problem_key, (path, payload) in sorted(latest_problem.items()):
        problem_id = str(payload.get("problem_id") or problem_key)
        db.upsert_research_record(
            f"problem:{problem_key}",
            kind="problem",
            domain="math",
            title=str(payload.get("title") or problem_id),
            status="open",
            source_path=path.relative_to(data).as_posix(),
            metadata={
                "problem_id": problem_id,
                "latest_campaign_id": payload.get("campaign_id"),
                "latest_phase": payload.get("phase"),
            },
        )
    return len(states), len(latest_problem)


def _index_papers(db: FactoryDB, data: Path) -> int:
    # The query index must expose truthful out-of-policy targets as draft/blocked records.
    # Submission and quality-gate callers retain strict target-policy enforcement.
    registry = load_registry(
        data,
        include_local_repositories=False,
        enforce_target_policy=False,
    )
    papers = registry.get("papers", {})
    for workspace, value in sorted(papers.items()):
        if not isinstance(value, dict):
            continue
        paper_id = str(value.get("paper_id") or Path(workspace).name)
        release = value.get("writing_release")
        release = release if isinstance(release, dict) else {}
        submission_state = value.get("submission_state")
        submission_state = submission_state if isinstance(submission_state, dict) else {}
        status = str(
            submission_state.get("current_status")
            or release.get("status")
            or value.get("record_status")
            or "draft"
        )
        db.upsert_research_record(
            f"paper:{paper_id}",
            kind="paper",
            domain=str(value.get("domain") or "unknown"),
            title=str(value.get("title") or paper_id),
            status=status,
            source_path=str(value.get("metadata_file") or f"registry/papers/{paper_id}.yaml"),
            metadata={
                "version": value.get("version"),
                "target_journal": value.get("target_journal"),
                "formatting_target": value.get("formatting_target"),
                "target_journal_tier": value.get("target_journal_tier"),
                "target_journal_ranking_system": value.get(
                    "target_journal_ranking_system"
                ),
                "target_policy_exception": value.get("target_policy_exception"),
                "manuscript_dir": value.get("manuscript_dir"),
                "writing_release_status": release.get("status"),
                "score": release.get("score"),
                "submission_history": value.get("submission_history", []),
                "submission_state": submission_state or None,
                "submission_preparation": value.get("submission_preparation"),
            },
        )
    return len(papers)


def _index_materials(db: FactoryDB, data: Path) -> int:
    count = 0
    for path in sorted((data / "workspaces" / "materials").glob("*/campaign_state.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        campaign_id = str(payload.get("campaign_id") or path.parent.name)
        title = str(payload.get("title") or campaign_id)
        status = str(payload.get("status") or "paused")
        relative = path.relative_to(data).as_posix()
        db.register_campaign(
            campaign_id,
            domain="materials",
            title=title,
            status=status,
            state_path=path.parent.relative_to(data).as_posix(),
            source=str(payload.get("source_system") or "materials"),
        )
        db.upsert_research_record(
            f"campaign:{campaign_id}",
            kind="campaign",
            domain="materials",
            title=title,
            status=status,
            source_path=relative,
            metadata={
                "phase": payload.get("phase"),
                "literature_audit": payload.get("literature_audit"),
                "legacy_artifacts": payload.get("legacy_artifacts"),
                "resume_guard": payload.get("resume_guard"),
            },
        )
        count += 1
    return count


def _write_exports(db: FactoryDB, database: Path) -> dict[str, Any]:
    export_root = database / "exports" / "current"
    records_path = atomic_write_json(
        export_root / "research-records.json",
        {"schema_version": "openlabs.research_records.export.v1", "records": db.research_records()},
    )
    campaigns_path = atomic_write_json(
        export_root / "campaigns.json",
        {"schema_version": "openlabs.campaigns.export.v1", "campaigns": db.campaigns()},
    )
    manifest = {
        "schema_version": "openlabs.database_export.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "files": [
            {"path": records_path.name, "sha256": _sha256(records_path)},
            {"path": campaigns_path.name, "sha256": _sha256(campaigns_path)},
        ],
        "counts": {
            "campaigns": len(db.campaigns()),
            "research_records": len(db.research_records()),
        },
    }
    atomic_write_json(export_root / "manifest.json", manifest)
    return manifest


def _write_legacy_artifact_manifest(artifacts: Path) -> dict[str, Any]:
    root = artifacts / "papers" / "legacy-ara-paper-writing"
    manifest_path = root / "manifest.json"
    entries = []
    for path in (sorted(root.rglob("*")) if root.is_dir() else []):
        if not path.is_file() or path == manifest_path:
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    payload = {
        "schema_version": "openlabs.artifact_manifest.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "ara-paper-writing current worktree",
        "policy": "local compatibility PDFs and archives; payloads ignored by Git",
        "files": entries,
    }
    atomic_write_json(manifest_path, payload)
    return {
        "path": manifest_path.relative_to(artifacts).as_posix(),
        "files": len(entries),
        "sha256": _sha256(manifest_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default=str(CODE_ROOT.parent))
    parser.add_argument("--amra-source")
    parser.add_argument("--paper-source")
    parser.add_argument("--ara-source")
    parser.add_argument("--aira-source")
    parser.add_argument("--materials-source")
    args = parser.parse_args()

    paths = workspace_paths(args.workspace)
    paths.ensure_runtime_directories()
    db = FactoryDB(paths.database_file)
    db.initialize()
    campaign_count, problem_count = _index_math(db, paths.data)
    materials_campaign_count = _index_materials(db, paths.data)
    paper_count = _index_papers(db, paths.data)
    export = _write_exports(db, paths.database)
    artifact_manifest = _write_legacy_artifact_manifest(paths.artifacts)

    supplied_sources = {
        "amra": args.amra_source,
        "ara-paper-writing": args.paper_source,
        "ara": args.ara_source,
        "aira": args.aira_source,
        "matfactory": args.materials_source,
    }
    migration_path = paths.data / "ledger" / "migrations" / "legacy-import-2026-08-07.json"
    previous_migration: dict[str, Any] = {}
    if migration_path.is_file():
        loaded = json.loads(migration_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            previous_migration = loaded
    previous_sources = previous_migration.get("source_repositories")
    source_state = dict(previous_sources) if isinstance(previous_sources, dict) else {}
    source_state.update({
        name: _git_state(Path(value).resolve())
        for name, value in supplied_sources.items()
        if value
    })
    migration = {
        "schema_version": "openlabs.legacy_migration.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "snapshot_semantics": (
            "Recorded commits are the import boundary. Status fingerprints identify later "
            "uncommitted source changes and do not imply that dirty files were imported."
        ),
        "source_repositories": source_state,
        "source_trees_modified": False,
        "imported": {
            "math_campaigns": campaign_count,
            "math_open_problem_families": problem_count,
            "materials_campaigns": materials_campaign_count,
            "materials_state_files": _count_files(
                paths.data / "workspaces" / "materials"
            ),
            "materials_literature_files": _count_files(
                paths.data / "literature" / "materials"
            ),
            "paper_registry_records": paper_count,
            "math_workspace_files": _count_files(paths.data / "workspaces" / "math"),
            "paper_source_files": _count_files(paths.data / "papers"),
            "review_files": _count_files(paths.data / "reviews"),
            "paper_binary_artifacts": artifact_manifest["files"],
        },
        "filters": {
            "code": "stable source, tests, protocols, Skills, and small frozen fixtures only",
            "paper_data": "committed import boundary; later dirty worktree changes excluded along with caches, replay environments/results, Lean .lake, PDFs, archives, and LaTeX build output",
            "paper_artifacts": "legacy PDFs and archives copied locally under artifacts and ignored by Git",
            "materials_state": "small supervisor/protocol/analysis state and literature audit imported; 23 GiB runtime evidence remains external and the campaign is paused",
            "database": "live SQLite ignored; portable JSON exports tracked",
        },
        "database_export": export,
        "artifact_manifest": artifact_manifest,
    }
    atomic_write_json(migration_path, migration)
    print(json.dumps(migration["imported"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
