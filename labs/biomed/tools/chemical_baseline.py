"""Run a bounded measured-activity baseline on an already curated chemical table.

The input must have compatible measured targets, standardized structures/identifiers and
frozen splits. Default evaluation uses validation only; test evaluation is explicit.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shlex
import sys
from pathlib import Path

from tools.common import CODE_ROOT, LAB_ROOT, atomic_json, sha256
from tools.split_audit import audit


def run(
    input_csv: Path,
    output_dir: Path,
    *,
    target: str,
    seed: int = 0,
    evaluate_test: bool = False,
    max_rows: int = 10_000,
) -> dict:
    import numpy as np
    from rdkit import Chem
    from rdkit.Chem import rdFingerprintGenerator
    from sklearn.dummy import DummyRegressor
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error, root_mean_squared_error

    if max_rows < 3 or max_rows > 10_000:
        raise ValueError("pilot max_rows must be 3..10000")
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(CODE_ROOT) or "openlabs-data" in output_dir.parts:
        raise ValueError("predictions belong in external artifact staging")
    overlap = audit(
        input_csv,
        independent_unit="molecule",
        strategy="scaffold",
        group_columns=["molecule_id", "scaffold_id"],
        max_rows=max_rows,
    )
    if not overlap["valid"]:
        raise ValueError("frozen split audit failed: " + "; ".join(overlap["errors"]))
    evaluation = "test" if evaluate_test else "validation"
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    features, labels, identities = {"train": [], evaluation: []}, {"train": [], evaluation: []}, []
    with input_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not {target, "standardized_smiles"}.issubset(reader.fieldnames or []):
            raise ValueError("curated target and standardized_smiles columns required")
        for row in reader:
            split = row["split"]
            if split not in features:
                continue  # Do not inspect or transform test labels/features in validation mode.
            value = float(row[target])
            if not math.isfinite(value):
                raise ValueError("target contains non-finite values")
            molecule = Chem.MolFromSmiles(row["standardized_smiles"])
            if molecule is None or molecule.GetNumAtoms() > 512:
                raise ValueError("invalid or oversized standardized molecule")
            features[split].append(generator.GetFingerprintAsNumPy(molecule))
            labels[split].append(value)
            if split == evaluation:
                identities.append(row["sample_id"])
    if len(labels["train"]) < 2 or len(labels[evaluation]) < 2:
        raise ValueError("at least two training and evaluation rows required for a smoke pilot")
    x_train = np.stack(features["train"])
    x_eval = np.stack(features[evaluation])
    models = {
        "median_predictor": DummyRegressor(strategy="median"),
        "morgan_random_forest": RandomForestRegressor(
            n_estimators=200,
            max_depth=12,
            min_samples_leaf=2,
            n_jobs=2,
            random_state=seed,
        ),
    }
    metrics, predictions = {}, {}
    for name, model in models.items():
        model.fit(x_train, labels["train"])
        predicted = model.predict(x_eval)
        predictions[name] = predicted
        metrics[name] = {
            "rmse": float(root_mean_squared_error(labels[evaluation], predicted)),
            "mae": float(mean_absolute_error(labels[evaluation], predicted)),
        }
    output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(output_dir / "split-audit.json", overlap)
    with (output_dir / "predictions.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "split", "measured_target", *models])
        for index, identity in enumerate(identities):
            writer.writerow(
                [
                    identity,
                    evaluation,
                    labels[evaluation][index],
                    *[predictions[name][index] for name in models],
                ]
            )
    results = {
        "stage": "exploratory_pilot",
        "independent_unit": "molecule",
        "metrics": metrics["morgan_random_forest"],
        "baselines": metrics,
        "trials_run": 2,
        "evaluation_partition": evaluation,
        "test_evaluated": evaluate_test,
        "limitations": [
            "One seed and two simple baselines; no confirmatory evidence or novelty claim.",
            "Assay compatibility, units, censoring and structure identities need upstream audit.",
            "No uncertainty intervals, biological mechanism or external replication established.",
        ],
        "run": {
            "command": shlex.join([sys.executable, *sys.argv]),
            "code_revision": "chemical_baseline.py:sha256:" + sha256(Path(__file__)),
            "seed": seed,
            "environment_sha256": sha256(LAB_ROOT / "uv.lock"),
        },
        "input_sha256": sha256(input_csv),
        "split_audit_sha256": sha256(output_dir / "split-audit.json"),
        "prediction_sha256": sha256(output_dir / "predictions.csv"),
        "model_parameters": {
            "morgan_radius": 2,
            "fingerprint_bits": 2048,
            "forest_trees": 200,
            "forest_max_depth": 12,
            "forest_min_samples_leaf": 2,
            "threads": 2,
        },
    }
    atomic_json(output_dir / "results.json", results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-rows", type=int, default=10_000)
    parser.add_argument("--evaluate-test", action="store_true")
    args = parser.parse_args()
    try:
        results = run(
            args.input,
            args.output_dir,
            target=args.target,
            seed=args.seed,
            evaluate_test=args.evaluate_test,
            max_rows=args.max_rows,
        )
        print(json.dumps(results))
        return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
