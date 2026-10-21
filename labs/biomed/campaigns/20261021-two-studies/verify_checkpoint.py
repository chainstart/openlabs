"""Read-only verification of saved day-one evidence; never refits a model."""

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import pandas as pd

WORKSPACE = Path("/home/biostar/work")
PROJECT = WORKSPACE / "openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021"
ARTIFACT = WORKSPACE / "openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    if path.stat().st_size > 1024**2:
        raise ValueError(f"Unexpected large metadata: {path}")
    return json.loads(path.read_text())


def main():
    result = read(PROJECT / "results.json")
    selection = read(PROJECT / "frozen-model-selection.json")
    index = read(PROJECT / "artifact-index.json")
    verified = []
    for entry in index["artifacts"]:
        uri = urlparse(entry["artifact_uri"])
        path = Path(unquote(uri.path)).resolve()
        assert uri.scheme == "file" and path.is_relative_to(ARTIFACT)
        assert path.stat().st_size == entry["bytes"]
        assert digest(path) == entry["sha256"]
        verified.append(path.name)
    for raw_path, expected in result["run"]["input_sha256"].items():
        path = Path(raw_path).resolve()
        assert path.is_relative_to(ARTIFACT) and path.stat().st_size < 256 * 1024**2
        assert digest(path) == expected
    assert digest(PROJECT / "plan.json") == result["run"]["plan_sha256"]
    assert digest(PROJECT / "environment.uv.lock") == result["run"]["environment_sha256"]
    axes = {}
    for axis, column in (("gene", "gene_id"), ("cell", "cell_line_id")):
        frame = pd.read_csv(PROJECT / f"{axis}-splits.csv")
        assert frame[column].is_unique
        assert set(frame["split"]) == {"train", "validation", "test"}
        axes[axis] = frame.groupby("split").size().to_dict()
    predictions_path = ARTIFACT / "test-predictions.csv.gz"
    assert predictions_path.stat().st_size < 16 * 1024**2
    frame = pd.read_csv(predictions_path)
    assert len(frame) <= 200000 and not frame.duplicated(["gene_id", "cell_line_id"]).any()
    assert len(frame) == result["sample_counts"]["test_pairs"]
    assert frame.gene_id.nunique() == axes["gene"]["test"]
    assert frame.cell_line_id.nunique() == axes["cell"]["test"]
    predicted = selection["affine_slope"] * frame.source + selection["affine_intercept"]
    errors = np.abs(frame.target.to_numpy() - predicted.to_numpy())
    assert np.allclose(errors, frame.calibrated_absolute_error, atol=1e-6, rtol=1e-6)
    tie = np.random.default_rng(20261021).random(len(frame))

    def retained(column, informative_only):
        mask = frame.informative if informative_only else np.ones(len(frame), bool)
        positions = np.flatnonzero(mask)
        ordered = positions[np.lexsort((tie[positions], frame[column].to_numpy()[positions]))]
        return ordered[: (len(ordered) + 1) // 2]

    means = {}
    for name in (result["selected_simple"], "hgb_risk", "ridge_risk"):
        means[name] = float(errors[retained(name, True)].mean())
    expected = result["metrics"]["informative_mae50_improvement_hgb_over_validation_best_simple"]
    assert abs(means[result["selected_simple"]] - means["hgb_risk"] - expected) < 1e-6
    global_keep = retained("hgb_risk", False)
    retained_information = int(frame.iloc[global_keep].informative.sum())
    secondary = read(PROJECT / "secondary-diagnostics.json")
    assert retained_information == secondary["retained_informative_pairs"]
    report = {
        "verification": "saved evidence, input hashes, axis uniqueness and metric arithmetic",
        "valid": True,
        "artifact_files_verified": verified,
        "axis_counts": axes,
        "recomputed_informative_mae50": means,
        "recomputed_informative_pairs_kept_by_pooled_hgb50": retained_information,
        "models_refitted": False,
        "new_scientific_confirmation": False,
        "generic_protocol_certified": False,
    }
    output = (
        WORKSPACE
        / "openlabs-artifacts/artifact-stage/biomed/campaign-20261021-literature"
        / "checkpoint-verification.json"
    )
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
