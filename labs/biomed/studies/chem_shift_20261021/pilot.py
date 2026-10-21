"""Frozen small assay-translation experiment; never opens reserved targets."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.linear_model import Ridge

HERE = Path(__file__).resolve().parent
ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021")


def main():
    plan_bytes = (HERE / "plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    (ROOT / "frozen-plan.json").write_bytes(plan_bytes)
    (ROOT / "environment.uv.lock").write_bytes((HERE.parents[1] / "uv.lock").read_bytes())
    eligible = json.loads((ROOT / "structure-feasibility.json").read_text())
    records = []
    exclusions = []
    predrows = []
    gen = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    for pair in eligible:
        if pair["target"] not in plan["development_targets"]:
            continue
        if pair["n_scaffolds"] < 6:
            continue
        frame = pd.read_csv(ROOT / pair["file"].replace(".", "-") / "data.csv.gz")
        subset = frame[frame.assay_chembl_id.isin([pair["a"], pair["b"]])]
        values = (
            subset.groupby(["compound_chembl_id", "assay_chembl_id"])
            .pchembl_value.median()
            .unstack()
            .dropna()
        )
        smiles = (
            subset.drop_duplicates("compound_chembl_id")
            .set_index("compound_chembl_id")
            .canonical_smiles
        )
        mols = [Chem.MolFromSmiles(smiles[c]) for c in values.index]
        assert all(x is not None for x in mols)
        scaffolds = np.array([MurckoScaffold.MurckoScaffoldSmiles(mol=m) for m in mols])
        fps = [gen.GetFingerprint(m) for m in mols]
        sim = np.array([DataStructs.BulkTanimotoSimilarity(fp, fps) for fp in fps])
        x = values[pair["a"]].to_numpy()
        y = values[pair["b"]].to_numpy()
        for seed in range(5):
            order = sorted(
                set(scaffolds), key=lambda s: hashlib.sha256(f"{seed}:{s}".encode()).hexdigest()
            )
            tests = set(order[: max(1, len(order) // 3)])
            test = np.flatnonzero(np.isin(scaffolds, list(tests)))
            pool = np.flatnonzero(~np.isin(scaffolds, list(tests)))
            if len(test) < 5 or len(pool) < 8:
                exclusions.append(
                    {
                        "target": pair["target"],
                        "a": pair["a"],
                        "seed": seed,
                        "n_test": len(test),
                        "n_pool": len(pool),
                    }
                )
                continue
            random = np.random.default_rng(seed).permutation(pool).tolist()
            far = [int(pool[0])]
            while len(far) < 8:
                rest = [int(i) for i in pool if i not in far]
                far.append(max(rest, key=lambda i: float(np.min(1 - sim[i, far]))))
            for budget in plan["anchor_budgets"]:
                for selection, ranking in [("random", random), ("maxmin", far)]:
                    anchors = np.array(ranking[:budget])
                    delta = y[anchors] - x[anchors]
                    offset = float(np.median(delta))
                    affine = Ridge(alpha=1).fit(x[anchors, None], y[anchors])
                    coef = np.linalg.solve(
                        sim[np.ix_(anchors, anchors)] + np.eye(budget), delta - offset
                    )
                    predictions = {
                        "identity": x[test],
                        "offset": x[test] + offset,
                        "affine": affine.predict(x[test, None]),
                        "structure_residual": x[test] + offset + sim[np.ix_(test, anchors)] @ coef,
                    }
                    for method, pred in predictions.items():
                        row = {
                            "target": pair["target"],
                            "assay_a": pair["a"],
                            "assay_b": pair["b"],
                            "seed": seed,
                            "budget": budget,
                            "selection": selection,
                            "method": method,
                            "n_test": len(test),
                            "mae": float(np.mean(abs(pred - y[test]))),
                            "rmse": float(np.mean((pred - y[test]) ** 2) ** 0.5),
                        }
                        records.append(row)
                        for i, p in zip(test, pred, strict=True):
                            predrows.append(
                                {
                                    **row,
                                    "compound": values.index[i],
                                    "prediction": float(p),
                                    "observed": float(y[i]),
                                    "source_activity": float(x[i]),
                                    "scaffold": scaffolds[i],
                                }
                            )
    df = pd.DataFrame(records)
    df.to_csv(ROOT / "pilot-metrics.csv", index=False)
    pd.DataFrame(predrows).to_csv(ROOT / "pilot-predictions.csv", index=False)
    targetmeans = df.groupby(["target", "budget", "selection", "method"]).mae.mean().reset_index()
    targetmeans.to_csv(ROOT / "pilot-target-means.csv", index=False)
    summary = {
        "stage": "exploratory_pilot",
        "paper_candidate": False,
        "trials_run": len(records),
        "independent_targets": df.target.nunique(),
        "assay_pairs": df[["assay_a", "assay_b"]].drop_duplicates().shape[0],
        "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "environment_sha256": hashlib.sha256(
            (ROOT / "environment.uv.lock").read_bytes()
        ).hexdigest(),
        "metrics": targetmeans.groupby(["budget", "selection", "method"])
        .mae.mean()
        .reset_index()
        .to_dict("records"),
        "excluded_splits": exclusions,
        "confirmatory_targets_opened": False,
        "limitations": [
            "Small derived corpus, not sufficient for publication readiness",
            "Source assay activity is known at inference",
            "Endpoint provenance in derived tables is not fully resolved",
            "Seeds and molecules are not independent target replications",
            "Only one assay orientation evaluated; not an experimental chronological transition",
            "No untouched confirmatory results used",
        ],
    }
    assert len(records) <= plan["max_trials"]
    (ROOT / "pilot-results.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
