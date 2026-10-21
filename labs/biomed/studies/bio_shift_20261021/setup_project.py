"""Freeze prospective pilot before inspecting the paired matrix outcomes."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(
    "/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021"
)
LAB = Path(__file__).resolve().parents[2]


def dump(name, obj):
    path = ROOT / name
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


ROOT.mkdir(parents=True, exist_ok=True)
if (ROOT / "plan.json").exists():
    raise SystemExit("Refusing to overwrite frozen plan")
plan = {
    "stage": "exploratory_pilot",
    "frozen_at_utc": datetime.now(UTC).isoformat(),
    "independent_unit": "gene_and_cell_line_crossed",
    "question": (
        "Can source-only numeric descriptors identify cross-laboratory dependency"
        " disagreement for target-label-unseen genes and cell lines, beyond "
        "effect magnitude and selectivity baselines, without discarding "
        "informative dependencies?"
    ),
    "primary_direction": "historical Broad CRISPRcleanR -> historical Sanger CRISPRcleanR",
    "primary_outcomes": [
        (
            "MAE of global affine calibrated replication at 50% retention inside "
            "source-defined informative dependency subset"
        ),
        "Same-retention paired improvement over strongest validation-selected simple risk score",
    ],
    "secondary_outcomes": [
        "risk coverage at 25/50/75/100%",
        "retained informative dependency fraction",
        "raw and calibrated residual sensitivity",
        "two-way gene/cell-line bootstrap intervals",
    ],
    "baselines": [
        "deterministic_random",
        "absolute_source_effect",
        "gene_standard_deviation",
        "absolute_source_contrast",
        "ridge_risk",
    ],
    "candidate_model": (
        "HistGradientBoostingRegressor(max_iter=80,max_leaf_nodes=15,max_depth=4,min_samples_leaf=100,learning_rate=.05,l2_regularization=1,random_state=20261021)"
    ),
    "split_strategy": "independent_hash_gene_and_cell_axes_60_20_20_diagonal_blocks",
    "group_columns": ["gene_id", "cell_line_id"],
    "split_seed": 20261021,
    "allowed_source_information": (
        "Full source matrix values are observed profiling covariates; gene "
        "descriptors use only TRAIN cell columns, cell descriptors only TRAIN "
        "genes. Test target outcomes and distribution are unavailable until final"
        " evaluation. Thus this is target-label cold-start, not unprofiled "
        "gene/cell cold-start."
    ),
    "target_information": (
        "Train target labels only gene-train x cell-train; validation only "
        "validation x validation; test only test x test. Off-diagonal target "
        "labels are never read into feature/model fits."
    ),
    "calibration": (
        "One global affine OLS mapping source to target using training block "
        "only; no per-gene target calibration."
    ),
    "features": [
        "source_value",
        "source_gene_mean_on_train_cells",
        "source_gene_sd_on_train_cells",
        "source_gene_q10_on_train_cells",
        "source_gene_q90_on_train_cells",
        "source_cell_mean_on_train_genes",
        "source_cell_sd_on_train_genes",
        "source_gene_centered_value",
        "source_gene_standardized_value",
    ],
    "informative_subset": (
        "Gene standard deviation above TRAIN-gene 75th percentile AND source "
        "value below its own gene mean minus one SD; threshold computed on "
        "source/train boundary only."
    ),
    "strong_effect_subset": "Source value below the training-block 10th percentile.",
    "training_cap_pairs": 200000,
    "risk_target": (
        "log1p(abs(target - affine(source))); inverse monotonic irrelevant for risk sorting"
    ),
    "selection": (
        "Select baseline ordering sign by validation only; compare HGB against "
        "strongest simple baseline chosen by validation informative MAE@50%. "
        "Ridge is separate matched ML comparator. No HGB hyperparameter tuning."
    ),
    "bootstrap": (
        "500 independent resamples of test gene IDs and cell IDs, applying "
        "product weights; selection thresholds and predictions frozen before "
        "resampling. Report gene/cell counts, not pairs as independent n."
    ),
    "leakage_controls": [
        "No target-lab integrated or qnorm matrices",
        "Full source profiling availability explicitly declared",
        "Split both axes with deterministic hashes before outcomes",
        "No test target statistics in transformations/selection",
        "No ordinary independent-pair bootstrap",
    ],
    "stop_conditions": [
        "Fewer than 60 exact-matched cell lines or 5000 genes",
        "Cell identity normalization ambiguous",
        "No informative validation or test subset with at least 20 genes and 10 cells",
        "Data/provenance boundary compromised",
        "No improvement over strongest simple comparator means negative pilot; do not promote",
    ],
    "confirmatory_holdout": (
        "Frozen test diagonal block is once-only internal pilot holdout; two "
        "historical laboratories do not establish generalization to a new "
        "laboratory. A third independent source is not yet acquired."
    ),
    "max_trials": 2,
    "resource_budget": {"cpu_threads": 2, "memory_mib": 1536, "scratch_mib": 2048},
    "campaign_start_utc": "2026-10-21T00:10:00Z",
    "campaign_deadline_utc": "2026-10-22T00:10:00Z",
    "publication_goal": (
        "Scientific quality aspiration from user: CAS major-category Zone 2 "
        "potential; no venue recommended or publication readiness established."
    ),
}
plan_ref = dump("plan.json", plan)
shutil.copyfile(LAB / "uv.lock", ROOT / "environment.uv.lock")
env_ref = {
    "path": "environment.uv.lock",
    "sha256": hashlib.sha256((ROOT / "environment.uv.lock").read_bytes()).hexdigest(),
}
dump(
    "project.json",
    {
        "schema_version": "openlabs.project.v1",
        "project_id": ROOT.name,
        "domain": "biology",
        "status": "active",
        "objective": plan["question"],
        "protocol": {"id": "biomed-public-data-pilot", "primary_skill": "biomed-research-loop"},
        "workstreams": [
            {
                "workstream_id": "cross-lab-risk",
                "state_path": "research_state.json",
                "startup": "paused",
                "agent_role": "researcher",
                "session_mode": "fresh",
                "objective": plan["question"],
                "resources": plan["resource_budget"],
                "wall_seconds": 7200,
                "max_agent_seconds": 86400,
            }
        ],
    },
)
dump(
    "research_state.json",
    {
        "schema_version": "openlabs.biomed_pilot_state.v1",
        "project_id": ROOT.name,
        "workstream_id": "cross-lab-risk",
        "status": "running",
        "research_question": plan["question"],
        "independent_unit": plan["independent_unit"],
        "paper_candidate": False,
        "next_experiment": (
            "Retrieve two named processed ZIP members using validated bounded HTTP "
            "ranges, audit identities, execute frozen pilot."
        ),
        "plan": plan_ref,
        "environment": env_ref,
        "datasets": [],
        "evidence": [],
        "claims": [],
        "protocol_status": (
            "not_validated: crossed axes and archive-range intake need explicit "
            "audit; no false passing claim"
        ),
        "worker_status": (
            "interactive guarded archive download sessions active; factory startup "
            "paused to prevent duplicate execution"
        ),
    },
)
print(json.dumps({"plan": plan_ref, "environment": env_ref}))
