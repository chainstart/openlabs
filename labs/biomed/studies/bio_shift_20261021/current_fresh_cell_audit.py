"Audit current official identity-only metadata against historical matrix headers."

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
    metadata = json.loads((ROOT / "current-cmp-identities.json").read_text())
    all_models = {model["model_id"]: model for model in metadata["models"]}
    old = set(pd.read_csv(PROJECT / "cell-splits.csv")["cell_line_id"])
    old_broad_map = pd.read_csv(ROOT / "author-cell-mapping/mapping.tsv", sep="\t", index_col=0)[
        "BROAD_ID"
    ].to_dict()
    matches = []
    ambiguous = []
    for model in all_models.values():
        b = set(model["identifiers"]) & broad
        s = set(model["names"]) & sanger
        if len(b) > 1 or len(s) > 1:
            if b and s:
                ambiguous.append(
                    {
                        "model_id": model["model_id"],
                        "broad_ids": sorted(b),
                        "sanger_names": sorted(s),
                    }
                )
            continue
        if b and s:
            matches.append(
                {
                    "model_id": model["model_id"],
                    "BROAD_ID": next(iter(b)),
                    "model_name": next(iter(s)),
                    "patient_id": model["patient_id"],
                    "parent_id": model["parent_id"],
                }
            )
    frame = pd.DataFrame(matches)
    duplicate = frame["BROAD_ID"].duplicated(keep=False) | frame["model_name"].duplicated(
        keep=False
    )
    duplicate_records = frame.loc[duplicate].to_dict("records")
    frame = frame.loc[~duplicate].copy()
    conflicts = []
    for row in frame.itertuples():
        if row.model_id in old and old_broad_map.get(row.model_id) != row.BROAD_ID:
            conflicts.append(
                {
                    "model_id": row.model_id,
                    "historical_ACH": old_broad_map.get(row.model_id),
                    "current_ACH": row.BROAD_ID,
                }
            )
    if conflicts:
        raise ValueError(f"Identity conflicts with prior mapping: {conflicts}")
    old_patients = {
        all_models[model]["patient_id"]
        for model in old
        if model in all_models and all_models[model]["patient_id"]
    }

    def family(model):
        seen = {model}
        while model in all_models and all_models[model]["parent_id"]:
            model = all_models[model]["parent_id"]
            if model in seen:
                raise ValueError("Cycle in recorded ancestry")
            seen.add(model)
        return seen

    old_family = set().union(*(family(model) for model in old))
    fresh = frame.loc[~frame["model_id"].isin(old)].copy()
    fresh["known_patient"] = fresh["patient_id"].notna()
    fresh["shared_patient_with_pilot"] = fresh["patient_id"].isin(old_patients)
    fresh["shared_recorded_ancestry_with_pilot"] = [
        bool(family(model) & old_family) for model in fresh["model_id"]
    ]
    fresh["eligible_by_recorded_patient_and_ancestry"] = fresh["known_patient"] & ~(
        fresh["shared_patient_with_pilot"] | fresh["shared_recorded_ancestry_with_pilot"]
    )
    fresh.to_csv(PROJECT / "current-fresh-cell-metadata.csv", index=False)
    report = {
        "stage": "metadata_only_no_new_target_computation",
        "official_models": len(all_models),
        "all_historical_broad_headers": len(broad),
        "all_historical_sanger_headers": len(sanger),
        "broad_headers_covered_by_current_official_identifiers": len(
            broad & set().union(*(set(model["identifiers"]) for model in all_models.values()))
        ),
        "sanger_headers_covered_by_current_official_names": len(
            sanger & set().union(*(set(model["names"]) for model in all_models.values()))
        ),
        "matched_one_to_one": len(frame),
        "old_pilot_cells": len(old),
        "old_pilot_ids_present_current_registry": len(old & set(all_models)),
        "fresh_matched_cells": len(fresh),
        "fresh_eligible_recorded_independent_cells": int(
            fresh["eligible_by_recorded_patient_and_ancestry"].sum()
        ),
        "fresh_patient_groups": int(
            fresh.loc[fresh["eligible_by_recorded_patient_and_ancestry"], "patient_id"].nunique()
        ),
        "ambiguous_multi_identifier_matches_excluded": ambiguous,
        "duplicate_cross_model_matches_excluded": duplicate_records,
        "identity_conflicts": conflicts,
        "target_numeric_values_accessed_this_audit": False,
        "limitations": [
            "Current registry is not an independent experimental study",
            "Recorded ancestry and patient IDs may be incomplete",
            (
                "Original pilot parsed whole TSV before selecting overlap; fresh "
                "cells were analytically unused, not cryptographically blinded"
            ),
            ("This audit does not authorize a second confirmatory use of the consumed test block"),
        ],
    }
    (PROJECT / "current-fresh-cell-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
