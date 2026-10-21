from __future__ import annotations

import csv

import pytest

pytest.importorskip("rdkit")
pytest.importorskip("sklearn")

from tools.chemical_baseline import run  # noqa: E402


def input_table(root, *, leaked=False):
    path = root / "curated.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["sample_id", "split", "molecule_id", "scaffold_id", "standardized_smiles", "activity"]
        )
        writer.writerows(
            [
                ["a", "train", "m1", "s1", "CCO", 1.0],
                ["b", "train", "m2", "s2", "c1ccccc1", 2.0],
                ["c", "validation", "m3", "s1" if leaked else "s3", "C1CCCCC1", 1.5],
                ["d", "validation", "m4", "s4", "c1ccncc1", 2.5],
                # Invalid values demonstrate that default evaluation does not inspect test data.
                ["e", "test", "m5", "s5", "invalid", "do-not-inspect"],
                ["f", "test", "m6", "s6", "invalid", "do-not-inspect"],
            ]
        )
    return path


def test_baseline_preserves_test_boundary_and_reports_both_baselines(tmp_path):
    result = run(input_table(tmp_path), tmp_path / "results", target="activity")
    assert result["evaluation_partition"] == "validation"
    assert result["test_evaluated"] is False
    assert set(result["baselines"]) == {"median_predictor", "morgan_random_forest"}
    assert (tmp_path / "results/predictions.csv").is_file()


def test_baseline_refuses_leakage_and_requires_explicit_usable_test_targets(tmp_path):
    with pytest.raises(ValueError, match="split audit failed"):
        run(input_table(tmp_path, leaked=True), tmp_path / "leaked", target="activity")
    with pytest.raises(ValueError):
        run(input_table(tmp_path), tmp_path / "test", target="activity", evaluate_test=True)
