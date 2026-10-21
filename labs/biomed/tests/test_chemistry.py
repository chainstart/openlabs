from __future__ import annotations

import csv

import pytest

pytest.importorskip("rdkit")

from tools.chemistry import prepare, standardize  # noqa: E402


def test_equivalent_smiles_and_salt_parent_have_same_identity():
    assert standardize("CCO")["molecule_id"] == standardize("OCC")["molecule_id"]
    assert standardize("CC(=O)[O-].[Na+]")["molecule_id"] == standardize("CC(=O)O")["molecule_id"]


def test_related_ring_molecules_share_scaffold_and_acyclics_are_grouped():
    assert standardize("Cc1ccccc1")["scaffold_id"] == standardize("Oc1ccccc1")["scaffold_id"]
    assert standardize("CCO")["scaffold_id"] == standardize("CCCO")["scaffold_id"]
    with pytest.raises(ValueError):
        standardize("not-a-molecule")


def test_rejected_rows_are_retained_without_changing_assay_labels(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("sample_id,smiles,activity\na,CCO,4.2\nb,invalid,3.1\n")
    report = prepare(source, tmp_path / "derived")
    assert report["counts"] == {"accepted": 1, "rejected": 1}
    with (tmp_path / "derived/prepared.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["activity"] == "4.2"
    assert "b" in (tmp_path / "derived/rejected.csv").read_text()
