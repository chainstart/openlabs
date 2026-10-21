# ruff: noqa: E501  # Literal provenance URLs and scientific state descriptions.
"""Pre-model pair eligibility; duplicate screening uses outcomes as a data-quality rule."""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(
    "/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021/chembl37"
)


def main():
    result = []
    for path in sorted(ROOT.glob("CHEMBL*-activities.json")):
        records = json.loads(path.read_text())
        df = pd.DataFrame(records)
        valid = df[
            (df.data_validity_comment.isna()) & (df.potential_duplicate.fillna(0).astype(int) == 0)
        ]
        valid = valid[
            (valid.standard_type == "IC50")
            & (valid.standard_units == "nM")
            & (valid.standard_relation == "=")
        ]
        valid = valid[valid.assay_type == "B"]
        valid = valid[
            ~valid.assay_description.fillna("").str.contains(
                "mutant|mutation|variant", case=False, regex=True
            )
        ]
        valid = valid.dropna(subset=["canonical_smiles", "pchembl_value", "document_chembl_id"])
        valid["pchembl_value"] = valid.pchembl_value.astype(float)
        tab = (
            valid.groupby(["molecule_chembl_id", "assay_chembl_id"])
            .pchembl_value.median()
            .unstack()
        )
        # Efficient candidate assay pairs from co-observed molecules, not N_assays squared.
        counts = {}
        for _, row in tab.iterrows():
            cols = row.dropna().index.tolist()
            for i, a in enumerate(cols):
                for b in cols[i + 1 :]:
                    counts[(a, b)] = counts.get((a, b), 0) + 1
        pairs = []
        for (a, b), n in counts.items():
            if n < 40:
                continue
            overlap = tab[[a, b]].dropna()
            docs_a = set(valid[valid.assay_chembl_id == a].document_chembl_id)
            docs_b = set(valid[valid.assay_chembl_id == b].document_chembl_id)
            equal = float(((overlap[a] - overlap[b]).abs() <= 0.02).mean())
            pairs.append(
                {
                    "a": a,
                    "b": b,
                    "common": n,
                    "documents_a": sorted(docs_a),
                    "documents_b": sorted(docs_b),
                    "cross_document": not bool(docs_a & docs_b),
                    "near_equal_fraction": equal,
                    "duplicate_screen_pass": equal < 0.8,
                }
            )
        result.append(
            {
                "target": path.stem.split("-")[0],
                "raw_records": len(df),
                "clean_binding_records": len(valid),
                "assays": valid.assay_chembl_id.nunique(),
                "pairs_at_least_40": pairs,
            }
        )
    report = {
        "status": "pre_model_metadata_and_duplicate_screening",
        "modeling_performed": False,
        "rules": "Exact IC50 nM, unflagged, Binding, non-mutant description; >=40 common; screen >80% values within 0.02 as likely re-citation, not an effect-based selection",
        "targets": result,
    }
    (ROOT / "pair-eligibility.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            [
                {
                    "target": t["target"],
                    "raw_records": t["raw_records"],
                    "pairs_at_least_40": len(t["pairs_at_least_40"]),
                    "cross_document_pairs": sum(
                        p["cross_document"] for p in t["pairs_at_least_40"]
                    ),
                }
                for t in result
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
