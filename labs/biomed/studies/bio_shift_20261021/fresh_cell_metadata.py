"Audit only matrix headers and official-author identity metadata; no target values."

import json
from pathlib import Path

import pandas as pd

ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021")
PROJECT = Path(
    "/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021"
)


def main():
    broad = set(pd.read_csv(ROOT / "broad/corrected_logFCs.tsv", sep="\t", nrows=0).columns) - {
        "Gene"
    }
    sanger = set(
        pd.read_csv(ROOT / "sanger/01_corrected_logFCs.tsv", sep="\t", nrows=0).columns
    ) - {"Gene"}
    models = pd.read_csv(ROOT / "author-full-model-metadata/models.csv", dtype=str)
    old = set(pd.read_csv(PROJECT / "cell-splits.csv")["cell_line_id"])
    # Exact official field matches only; no fuzzy alias or version joining.
    matches = models.loc[models["BROAD_ID"].isin(broad) & models["model_name"].isin(sanger)].copy()
    ambiguous = (
        matches["model_id"].duplicated(keep=False)
        | matches["BROAD_ID"].duplicated(keep=False)
        | matches["model_name"].duplicated(keep=False)
    )
    excluded_ambiguous = matches.loc[ambiguous, ["model_id", "BROAD_ID", "model_name"]].to_dict(
        "records"
    )
    matches = matches.loc[~ambiguous]
    old_rows = models.loc[models["model_id"].isin(old)]
    old_patients = set(old_rows["patient_id"].dropna())
    fresh = matches.loc[~matches["model_id"].isin(old)].copy()
    fresh["shared_patient_with_pilot"] = fresh["patient_id"].isin(old_patients)
    fresh["patient_unknown"] = fresh["patient_id"].isna()
    parents = models.set_index("model_id")["parent_id"].dropna().to_dict()

    def family(model):
        family = {model}
        while model in parents:
            model = parents[model]
            if model in family:
                raise ValueError("Cycle in model ancestry")
            family.add(model)
        return family

    old_family = set().union(*(family(model) for model in old))
    fresh["shared_recorded_ancestry_with_pilot"] = [
        bool(family(model) & old_family) for model in fresh["model_id"]
    ]
    fresh["eligible_under_recorded_donor_ancestry"] = ~(
        fresh["shared_patient_with_pilot"]
        | fresh["patient_unknown"]
        | fresh["shared_recorded_ancestry_with_pilot"]
    )
    # Only identity and study grouping fields, not phenotype/assay outcomes.
    columns = [
        "model_id",
        "model_name",
        "BROAD_ID",
        "parent_id",
        "patient_id",
        "tissue",
        "cancer_type",
        "shared_patient_with_pilot",
        "patient_unknown",
        "shared_recorded_ancestry_with_pilot",
        "eligible_under_recorded_donor_ancestry",
    ]
    fresh[columns].to_csv(PROJECT / "fresh-cell-metadata.csv", index=False)
    report = {
        "stage": "metadata_only_after_negative_pilot",
        "broad_header_cells": len(broad),
        "sanger_header_cells": len(sanger),
        "full_model_metadata_rows": len(models),
        "exact_one_to_one_matched_cells": len(matches),
        "pilot_cells": len(old),
        "additional_exact_matched_cells": len(fresh),
        ("additional_cells_with_known_nonoverlapping_patient_and_no_recorded_shared_ancestry"): int(
            fresh["eligible_under_recorded_donor_ancestry"].sum()
        ),
        "additional_patient_groups": int(
            fresh.loc[fresh["eligible_under_recorded_donor_ancestry"], "patient_id"].nunique()
        ),
        "ambiguous_exact_matches_excluded": excluded_ambiguous,
        "target_numeric_values_accessed_this_audit": False,
        "boundary_warning": (
            "The first pilot loader parsed the entire original target TSV "
            "before selecting the original-author overlap columns. Extra-cell"
            " target values were not used in numerical statistics, model "
            "fitting, selection or reporting. These are analytically unused "
            "logical holdouts, not byte-level unopened or cryptographically "
            "blinded data. Exact identity and recorded ancestry do not prove "
            "complete donor independence."
        ),
    }
    (PROJECT / "fresh-cell-metadata-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
