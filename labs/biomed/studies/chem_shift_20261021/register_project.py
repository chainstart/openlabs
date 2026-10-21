# ruff: noqa: E501  # Literal provenance URLs and scientific state descriptions.
"""Register truthful running state; publication and completed-pilot gates remain shut."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.common import atomic_json

HERE = Path(__file__).resolve().parent
DEST = Path(
    "/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-chem-shift-20261021"
)
ART = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021")


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    question = "Does structure-only anchor selection improve same-molecule cross-assay translation on unrepresented scaffolds at fixed paired-label budgets?"
    plan = json.loads((HERE / "plan.json").read_text())
    plan.update(
        independent_unit="molecule",
        inferential_unit="target; nested assay pairs and repeated seeds are not independent",
        primary_outcomes=["MAE relative to identity and matched-anchor median offset"],
        baselines=plan["methods"],
        group_columns=["molecule_id", "scaffold_id"],
        split_strategy="scaffold",
        leakage_controls=[
            "Source activity known at inference, explicitly paired translation",
            "No test scaffold in anchor pool",
            "No target outcomes used for acquisition eligibility",
            "Five reserved ChEMBL32 targets remain unopened",
        ],
        confirmatory_holdout="Reserved ChEMBL32 targets untouched; no confirmation admitted because source independence and power gates failed",
        protocol_limitations="Generic protocol does not model nested target inference or two-way paired translation; no completed protocol claim is made",
        current_phase="Replan after derived-data pilot failure; acquiring fixed ChEMBL37 targets",
    )
    atomic_json(DEST / "plan.json", plan)
    lock = (HERE.parents[1] / "uv.lock").read_bytes()
    (DEST / "environment.uv.lock").write_bytes(lock)
    (DEST / "development-pilot-results.json").write_bytes((ART / "pilot-results.json").read_bytes())
    project = {
        "schema_version": "openlabs.project.v1",
        "project_id": DEST.name,
        "domain": "biology",
        "status": "active",
        "objective": question,
        "protocol": {"id": "biomed-public-data-pilot", "primary_skill": "biomed-research-loop"},
        "workstreams": [
            {
                "workstream_id": "chem-assay-shift",
                "state_path": "research_state.json",
                "startup": "paused",
                "agent_role": "researcher",
                "session_mode": "fresh",
                "objective": "Acquire bounded fixed-target ChEMBL37 data, audit source-independent assay pairs, stop if no independent evidence",
                "resources": {"cpu_threads": 2, "memory_mib": 1536, "scratch_mib": 512},
                "wall_seconds": 3600,
                "max_agent_seconds": 86400,
            }
        ],
    }
    atomic_json(DEST / "project.json", project)
    state = {
        "schema_version": "openlabs.biomed_pilot_state.v1",
        "project_id": DEST.name,
        "workstream_id": "chem-assay-shift",
        "status": "running",
        "research_question": question,
        "independent_unit": "molecule",
        "paper_candidate": False,
        "sampling_unit": "paired molecule-assay measurement",
        "inferential_unit": "target; nested assays and seeds are dependent; molecule field is protocol sampling-unit compatibility only, not an independence claim",
        "next_experiment": "Complete actual guarded ChEMBL37 acquisition, then assess assay/source independence without opening reserved targets",
        "plan": {
            "path": "plan.json",
            "sha256": hashlib.sha256((DEST / "plan.json").read_bytes()).hexdigest(),
        },
        "environment": {"path": "environment.uv.lock", "sha256": hashlib.sha256(lock).hexdigest()},
        "datasets": [],
        "evidence": [],
        "claims": [],
        "negative_results": [
            {
                "file": "development-pilot-results.json",
                "reason": "Four-target pilot identity MAE approximately 0.006, suggesting re-cited or nearly duplicated source measurements; no useful transfer claim",
            }
        ],
        "worker": {
            "kind": "guarded_direct_process",
            "acquisition_script": str(HERE / "expand_intake.py"),
            "session_id": 59331,
        },
        "factory_startup": "paused to prevent duplicate execution; direct guarded acquisition is running",
        "journal_target_status": "User explicitly requests 2025 CAS major-category Zone 2 aspiration for this campaign; no specific journal recommended and no venue gate attempted",
        "target_aspiration": {
            "ranking_year": 2025,
            "ranking_scope": "major_category",
            "zone": 2,
            "verified_candidate": False,
        },
    }
    atomic_json(DEST / "research_state.json", state)
    print(DEST)


if __name__ == "__main__":
    main()
