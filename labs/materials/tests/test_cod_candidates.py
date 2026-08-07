from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.cod_candidates import (
    expected_composition_from_metadata,
    load_cod_harvest_protocol,
    screen_cod_cif,
)

PROTOCOL = ROOT / "analysis/protocols/cod_hidden_order_harvest_v1.json"


def test_declared_formula_times_z_restores_exact_llzto_cell():
    composition = expected_composition_from_metadata(
        {
            "formula": "- La3 Li6.5 O12 Ta0.5 Zr1.5 -",
            "Z": "8",
            "cellformula": "- La24 Li51.36 O96 Ta3.872 Zr12.144 -",
        }
    )
    assert composition == {
        "La": 24.0,
        "Li": 52.0,
        "O": 96.0,
        "Ta": 4.0,
        "Zr": 12.0,
    }


def test_llzto_cif_passes_disorder_screen_when_size_limit_allows(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["max_expected_ordered_atoms"] = 256
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(payload), encoding="utf-8")
    protocol = load_cod_harvest_protocol(protocol_path)
    metadata = {
        "file": "1545083",
        "formula": "- La3 Li6.5 O12 Ta0.5 Zr1.5 -",
        "cellformula": "- La24 Li51.36 O96 Ta3.872 Zr12.144 -",
        "Z": "8",
        "title": "LLZTO",
        "year": "2016",
        "sg": "I a -3 d",
        "sgNumber": "230",
    }
    text = (ROOT / "data/structures/raw/cod_1545083.cif").read_text(encoding="utf-8")
    record = screen_cod_cif(metadata, text, protocol)
    assert record["passes_automatic_screen"]
    assert record["n_disordered_sites"] == 136
    assert record["n_mixed_species_sites"] == 16
    assert record["n_vacancy_bearing_sites"] == 120
    assert record["maximum_composition_error_atoms"] == pytest.approx(0.64)
    assert record["manual_novelty_review_required"]


def test_default_protocol_is_bounded_and_zero_gpu():
    protocol = load_cod_harvest_protocol(PROTOCOL)
    assert protocol.max_workers <= 4
    assert protocol.max_downloads == 100
    assert protocol.max_selected == 30
    assert protocol.max_expected_ordered_atoms == 160


def test_selected_count_cannot_exceed_download_count(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["max_downloads"] = 5
    payload["max_selected"] = 6
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cannot exceed"):
        load_cod_harvest_protocol(path)
