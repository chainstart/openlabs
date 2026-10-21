"""Create a paused chemistry generalization pilot; never enqueue or run research."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from tools.common import CODE_ROOT, LAB_ROOT, atomic_json, identifier, sha256


def initialize(data_root: Path, project_id: str) -> Path:
    identifier(project_id)
    data_root = data_root.resolve()
    if data_root.is_relative_to(CODE_ROOT):
        raise ValueError("research state must be outside code Git")
    lock = LAB_ROOT / "uv.lock"
    if not lock.is_file():
        raise ValueError("resolve and lock the base environment before creating a pilot")
    root = data_root / "workspaces" / "biology" / "projects" / project_id
    root.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(lock, root / "environment.uv.lock")
    plan = {
        "stage": "exploratory_pilot",
        "independent_unit": "molecule",
        "primary_outcomes": [
            "Predictive error on unseen chemical scaffolds",
            "Uncertainty calibration",
        ],
        "baselines": ["median_predictor", "morgan_random_forest"],
        "split_strategy": "scaffold",
        "group_columns": ["molecule_id", "scaffold_id"],
        "leakage_controls": [
            "Standardize structures and audit duplicated molecule/assay/publication records",
            "Keep molecules and scaffolds disjoint across train/validation/test",
            "Fit transformations and choose hyperparameters within training/validation only",
            "Resolve ChEMBL/PubChem upstream overlap before claiming external validation",
        ],
        "stop_conditions": [
            "No defensible literature gap or compatible assay subset",
            "Insufficient independent scaffolds for meaningful evaluation",
            "Resource budget exceeded or provenance/holdout compromised",
            "At most six exploratory trials; replan before extending the search",
        ],
        "confirmatory_holdout": (
            "Not acquired or inspected. Select and register an independent assay/study or later "
            "time period only after the literature and overlap audit; pilot test data cannot "
            "become confirmatory evidence."
        ),
        "max_trials": 6,
        "resource_budget": {"cpu_threads": 2, "memory_mib": 3072, "scratch_mib": 2048},
    }
    atomic_json(root / "plan.json", plan)
    state = {
        "schema_version": "openlabs.biomed_pilot_state.v1",
        "project_id": project_id,
        "workstream_id": "chem-generalization",
        "status": "configured",
        "research_question": (
            "Can a modest uncertainty-aware predictor identify unreliable activity predictions "
            "on unseen chemical scaffolds under matched training budgets?"
        ),
        "independent_unit": "molecule",
        "paper_candidate": False,
        "next_experiment": (
            "Audit recent literature and select one target/assay family with compatible activity "
            "definitions; record a dated data release and assess independent scaffold counts "
            "before downloading a modeling cohort."
        ),
        "plan": {"path": "plan.json", "sha256": sha256(root / "plan.json")},
        "environment": {
            "path": "environment.uv.lock",
            "sha256": sha256(root / "environment.uv.lock"),
        },
        "datasets": [],
        "evidence": [],
        "claims": [],
    }
    atomic_json(root / "research_state.json", state)
    project = {
        "schema_version": "openlabs.project.v1",
        "project_id": project_id,
        "domain": "biology",
        "status": "paused",
        "objective": state["research_question"],
        "protocol": {"id": "biomed-public-data-pilot", "primary_skill": "biomed-research-loop"},
        "workstreams": [
            {
                "workstream_id": "chem-generalization",
                "state_path": "research_state.json",
                "startup": "paused",
                "agent_role": "researcher",
                "session_mode": "fresh",
                "objective": state["next_experiment"],
                "resources": plan["resource_budget"],
                "wall_seconds": 1800,
                "max_agent_seconds": 7200,
            }
        ],
    }
    atomic_json(root / "project.json", project)
    return root / "project.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--project-id", default="biomed-chem-generalization-pilot")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                {
                    "valid": True,
                    "startup": "paused",
                    "project": str(initialize(args.data_root, args.project_id)),
                }
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
