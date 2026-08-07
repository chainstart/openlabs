"""Tests for loading and summarising the experiment/MLIP comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.compare import load_experimental, summarise  # noqa: E402


def _write(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "facts.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return path


def _record(ea, *, sigma=None, cls="ceramic", doi="10.1/x", sample="S",
            chemistry="garnet"):
    properties = {}
    if ea is not None:
        properties["activation_energy"] = {"value": ea, "error": None, "raw": str(ea)}
    if sigma is not None:
        properties["total_conductivity"] = {"value": sigma, "error": None, "raw": "s"}
    return {
        "sample": sample,
        "properties": properties,
        "doi": doi,
        "doc_id": "d1",
        "year": 2024,
        "table_index": 0,
        "table_offset": 10,
        "material_class": cls,
        "chemistry": chemistry,
    }


class TestLoadExperimental:
    def test_reads_activation_energies(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.26)])
        points = load_experimental(path)
        assert [p.activation_energy_ev for p in points] == [0.31, 0.26]

    def test_polymer_records_are_excluded_by_default(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.09, cls="polymer")])
        points = load_experimental(path)
        assert [p.activation_energy_ev for p in points] == [0.31]

    def test_polymer_records_can_be_requested(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.09, cls="polymer")])
        points = load_experimental(path, material_class="polymer")
        assert [p.activation_energy_ev for p in points] == [0.09]

    def test_all_classes_when_filter_disabled(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.09, cls="polymer")])
        assert len(load_experimental(path, material_class=None)) == 2

    def test_records_without_activation_energy_are_skipped(self, tmp_path):
        path = _write(tmp_path, [_record(None, sigma=1e-4), _record(0.31)])
        assert len(load_experimental(path)) == 1

    def test_conductivity_can_be_required(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.26, sigma=1e-3)])
        points = load_experimental(path, require_conductivity=True)
        assert [p.conductivity_s_cm for p in points] == [1e-3]

    def test_provenance_survives_loading(self, tmp_path):
        path = _write(tmp_path, [_record(0.31, doi="10.1039/abc")])
        point = load_experimental(path)[0]
        assert point.doi == "10.1039/abc"
        assert point.doc_id == "d1"
        assert point.table_offset == 10

    def test_blank_lines_are_tolerated(self, tmp_path):
        path = tmp_path / "f.jsonl"
        path.write_text(json.dumps(_record(0.31)) + "\n\n", encoding="utf-8")
        assert len(load_experimental(path)) == 1


class TestChemistryFilter:
    def test_nasicon_is_excluded_from_the_garnet_default(self, tmp_path):
        # NZSP conducts Na near 0.14 eV; letting it in drags the garnet mean down.
        path = _write(tmp_path, [
            _record(0.31),
            _record(0.13, chemistry="nasicon-na", sample="NZSP-86"),
        ])
        points = load_experimental(path)
        assert [p.activation_energy_ev for p in points] == [0.31]

    def test_latp_is_excluded_too(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.40, chemistry="nasicon-li")])
        assert len(load_experimental(path)) == 1

    def test_a_family_can_be_requested(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.13, chemistry="nasicon-na")])
        points = load_experimental(path, chemistry="nasicon-na")
        assert [p.activation_energy_ev for p in points] == [0.13]

    def test_filter_can_be_disabled(self, tmp_path):
        path = _write(tmp_path, [_record(0.31), _record(0.13, chemistry="nasicon-na")])
        assert len(load_experimental(path, chemistry=None)) == 2

    def test_unlabelled_records_are_excluded_from_strict_default(self, tmp_path):
        record = _record(0.31)
        del record["chemistry"]
        path = _write(tmp_path, [record])
        assert load_experimental(path) == []

    def test_unlabelled_records_can_be_loaded_explicitly(self, tmp_path):
        record = _record(0.31)
        del record["chemistry"]
        path = _write(tmp_path, [record])
        points = load_experimental(path, allow_unlabelled=True)
        assert len(points) == 1
        assert points[0].chemistry is None

    def test_chemistry_is_carried_onto_the_point(self, tmp_path):
        path = _write(tmp_path, [_record(0.31)])
        assert load_experimental(path)[0].chemistry == "garnet"


class TestSummarise:
    def test_empty_input(self):
        assert summarise([]) == {}

    def test_single_value_has_zero_spread(self):
        stats = summarise([0.3])
        assert stats["n"] == 1
        assert stats["std"] == 0.0
        assert stats["mean"] == pytest.approx(0.3)

    def test_known_mean_and_sample_std(self):
        stats = summarise([0.2, 0.3, 0.4])
        assert stats["mean"] == pytest.approx(0.3)
        assert stats["std"] == pytest.approx(0.1)  # sample std, n-1
        assert stats["median"] == pytest.approx(0.3)

    def test_extremes_are_reported(self):
        stats = summarise([0.22, 0.31, 0.42])
        assert stats["min"] == 0.22
        assert stats["max"] == 0.42
