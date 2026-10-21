"""Synthetic invariance check: changing only held-out labels cannot change selection."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from run_pilot import axis_part


def main():
    if "openlabs-workers.slice" not in Path("/proc/self/cgroup").read_text():
        raise RuntimeError("This validation and both children require inherited guard")
    rng = np.random.default_rng(73)
    genes = np.array([f"GENE{i:05}" for i in range(5000)])
    cells = np.array([f"SIDM{i:05}" for i in range(120)])
    src = rng.normal(size=(5000, 120)) * rng.uniform(0.2, 2, (5000, 1))
    target = 0.8 * src + 0.2 + rng.normal(size=src.shape) * (0.05 + 0.2 * np.abs(src))
    gp = np.array([axis_part(g, "gene") for g in genes])
    cp = np.array([axis_part(c, "cell") for c in cells])
    selections = []
    with tempfile.TemporaryDirectory(prefix="openlabs-bio-risk-validation-") as temp:
        for attempt in range(2):
            root = Path(temp) / str(attempt)
            for name in ["broad", "sanger", "author-cell-mapping", "project"]:
                (root / name).mkdir(parents=True)
            pd.DataFrame(src, index=genes, columns=[f"ACH-{i:06}" for i in range(120)]).to_csv(
                root / "broad/corrected_logFCs.tsv", sep="\t"
            )
            y = target.copy()
            if attempt:
                y[np.ix_(gp == 2, cp == 2)] += 100
            pd.DataFrame(y, index=genes, columns=[f"CELL-{i}" for i in range(120)]).to_csv(
                root / "sanger/01_corrected_logFCs.tsv", sep="\t"
            )
            pd.DataFrame(
                {
                    "BROAD_ID": [f"ACH-{i:06}" for i in range(120)],
                    "model_name": [f"CELL-{i}" for i in range(120)],
                },
                index=cells,
            ).to_csv(root / "author-cell-mapping/mapping.tsv", sep="\t")
            for name in ["plan.json", "environment.uv.lock", "preprocessing-addendum.json"]:
                (root / "project" / name).write_text("software validation only\n")
            subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("run_pilot.py")),
                    "--root",
                    str(root),
                    "--project",
                    str(root / "project"),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            selection = json.loads((root / "frozen-model-selection.json").read_text())
            selection.pop("selection_time_unix")
            selections.append(selection)
    if selections[0] != selections[1]:
        raise AssertionError("Held-out target labels changed train/validation selection")
    print(
        json.dumps(
            {
                "software_validation": True,
                "synthetic_data": True,
                "scientific_result": False,
                "heldout_label_change_does_not_change_selection": True,
                "runs": 2,
            }
        )
    )


if __name__ == "__main__":
    main()
