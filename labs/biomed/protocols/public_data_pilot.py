"""Validate exploratory biomed evidence, without granting scientific or paper approval."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.common import file_record, read_json  # noqa: E402
from tools.dataset_intake import validate_manifest  # noqa: E402
from tools.split_audit import STRATEGIES, UNIT_COLUMNS, audit  # noqa: E402

PROTOCOL = {"id": "biomed-public-data-pilot", "primary_skill": "biomed-research-loop"}


def nonempty_list(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def numeric_metrics(value) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and all(
            isinstance(key, str)
            and key.strip()
            and isinstance(number, (int, float))
            and not isinstance(number, bool)
            and math.isfinite(number)
            for key, number in value.items()
        )
    )


def validate(project_path: Path, workstream_path: Path, mode: str = "commit") -> list[str]:
    errors = []
    project_path = project_path.resolve()
    root = project_path.parent
    project = read_json(project_path)
    state = read_json(workstream_path)
    if mode not in {"discovery", "commit"}:
        return ["unknown validation mode"]
    if project.get("schema_version") != "openlabs.project.v1" or project.get("domain") != "biology":
        errors.append("biology project required")
    if project.get("protocol") != PROTOCOL:
        errors.append("incorrect biomed protocol binding")
    if project.get("status") not in {"active", "paused", "retired"}:
        errors.append("invalid project status")
    declared = []
    for item in project.get("workstreams", []):
        if isinstance(item, dict):
            try:
                path = file_record_path(root, item.get("state_path"))
                declared.append((path, item.get("workstream_id")))
            except ValueError as exc:
                errors.append(str(exc))
    if (workstream_path.resolve(), state.get("workstream_id")) not in declared:
        errors.append("undeclared workstream or identity mismatch")
    if not project.get("project_id") or state.get("project_id") != project.get("project_id"):
        errors.append("project identity mismatch")
    if state.get("schema_version") != "openlabs.biomed_pilot_state.v1":
        errors.append("unknown state schema")
    if state.get("paper_candidate") is not False:
        errors.append("exploratory pilot cannot be a paper candidate")
    if state.get("status") not in {"configured", "running", "completed", "failed", "needs_replan"}:
        errors.append("invalid pilot status")
    for field in ("research_question", "independent_unit", "next_experiment"):
        if not isinstance(state.get(field), str) or not state[field].strip():
            errors.append(f"{field} required")

    documents = {}
    for field in ("plan", "environment"):
        try:
            path = file_record(root, state.get(field))
            documents[field] = read_json(path) if field == "plan" else path
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"{field}: {exc}")
    plan = documents.get("plan", {})
    if plan:
        if plan.get("stage") != "exploratory_pilot":
            errors.append("plan must be exploratory")
        for field in (
            "primary_outcomes",
            "baselines",
            "leakage_controls",
            "stop_conditions",
            "group_columns",
        ):
            if not nonempty_list(plan.get(field)):
                errors.append(f"plan {field}: nonempty string list required")
        if plan.get("independent_unit") not in UNIT_COLUMNS or plan.get(
            "independent_unit"
        ) != state.get("independent_unit"):
            errors.append("invalid or mismatched independent unit")
        if plan.get("split_strategy") not in STRATEGIES:
            errors.append("unsupported split strategy")
        groups = plan.get("group_columns", [])
        if isinstance(groups, list):
            required = UNIT_COLUMNS.get(plan.get("independent_unit"))
            if required not in groups or len(groups) != len(set(map(str, groups))):
                errors.append("plan must group on unique independent-unit columns")
            for strategy, column in (("scaffold", "scaffold_id"), ("study", "study_id")):
                if plan.get("split_strategy") == strategy and column not in groups:
                    errors.append(f"{strategy} strategy requires {column}")
        if (
            not isinstance(plan.get("confirmatory_holdout"), str)
            or not plan["confirmatory_holdout"].strip()
        ):
            errors.append("explicit untouched confirmatory holdout boundary required")
        trials = plan.get("max_trials")
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            errors.append("positive max_trials required")
        budget = plan.get("resource_budget", {})
        for field in ("cpu_threads", "memory_mib", "scratch_mib"):
            value = budget.get(field) if isinstance(budget, dict) else None
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                errors.append(f"positive resource_budget.{field} required")

    completed = state.get("status") == "completed"
    for field in ("datasets", "evidence", "claims"):
        if not isinstance(state.get(field), list):
            errors.append(f"{field} must be a list")
    datasets = state.get("datasets", [])
    if isinstance(datasets, list):
        if completed and not datasets:
            errors.append("completed pilot requires dataset manifests")
        for record in datasets:
            try:
                manifest = read_json(file_record(root, record))
                errors.extend(validate_manifest(manifest, verify_payload=completed))
                if completed and "unknown" in manifest.get("upstream_study_ids", []):
                    errors.append("resolve upstream study overlap before completing a pilot")
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"dataset: {exc}")
    evidence = state.get("evidence", [])
    if isinstance(evidence, list):
        for record in evidence:
            try:
                file_record(root, record)
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"evidence: {exc}")
        if completed and not evidence:
            errors.append("completed pilot requires hash-bound evidence")
    claims = state.get("claims", [])
    if isinstance(claims, list):
        for claim in claims:
            if (
                not isinstance(claim, dict)
                or claim.get("status")
                not in {
                    "hypothesis",
                    "provisional",
                    "refuted",
                }
                or not isinstance(claim.get("text"), str)
                or not claim["text"].strip()
            ):
                errors.append("pilot claims require text and hypothesis/provisional/refuted status")
            elif claim["status"] != "hypothesis" and not evidence:
                errors.append("observed claim requires hash-bound evidence")

    if completed and plan:
        try:
            split_report = read_json(file_record(root, state.get("split_audit")))
            samples = file_record(root, split_report.get("sample_table"))
            recomputed = audit(
                samples,
                independent_unit=plan["independent_unit"],
                group_columns=plan["group_columns"],
                strategy=plan["split_strategy"],
                project_root=root,
            )
            if split_report != recomputed or not recomputed["valid"]:
                errors.append("split audit differs from recomputation or contains leakage")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"split_audit: {exc}")
        try:
            results = read_json(file_record(root, state.get("results")))
            if results.get("stage") != "exploratory_pilot":
                errors.append("results must be exploratory")
            if results.get("independent_unit") != plan["independent_unit"]:
                errors.append("results unit mismatch")
            if not numeric_metrics(results.get("metrics")):
                errors.append("nonempty finite result metrics required")
            baselines = results.get("baselines", {})
            if not isinstance(baselines, dict) or any(
                not numeric_metrics(baselines.get(name)) for name in plan["baselines"]
            ):
                errors.append("metrics required for all planned baselines")
            trials = results.get("trials_run")
            if (
                isinstance(trials, bool)
                or not isinstance(trials, int)
                or not 1 <= trials <= plan["max_trials"]
            ):
                errors.append("trials_run must respect frozen max_trials")
            if not nonempty_list(results.get("limitations")):
                errors.append("result limitations required")
            run = results.get("run", {})
            if not isinstance(run, dict):
                raise ValueError("run record required")
            for field in ("command", "code_revision"):
                if not isinstance(run.get(field), str) or not run[field].strip():
                    errors.append(f"run.{field} required")
            if isinstance(run.get("seed"), bool) or not isinstance(run.get("seed"), int):
                errors.append("integer run.seed required")
            if run.get("environment_sha256") != state["environment"]["sha256"]:
                errors.append("run environment hash mismatch")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"results: {exc}")
    return errors


def file_record_path(root: Path, raw: str) -> Path:
    from tools.common import confined

    return confined(root, raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--workstream", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["discovery", "commit"])
    args = parser.parse_args()
    try:
        errors = validate(args.project, args.workstream, args.mode)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors = [str(exc)]
    print(json.dumps({"valid": not errors, "errors": errors}))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
