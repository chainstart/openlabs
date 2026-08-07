from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.orderings import (
    _load_disordered,
    enumerate_exact_orderings,
    load_ordering_protocol,
    run_ordering_campaign,
)

PROTOCOL = ROOT / "analysis/protocols/hidden_order_enumeration_v1.json"


def test_generic_milp_orders_llzto_at_exact_cell_composition():
    structure, _warnings = _load_disordered(
        ROOT / "data/structures/raw/cod_1545083.cif"
    )
    target = {"Li": 52, "La": 24, "Zr": 12, "Ta": 4, "O": 96}
    ordered, records = enumerate_exact_orderings(
        structure,
        target,
        max_solutions=2,
        seed_start=71,
        max_attempts_multiplier=5,
        minimum_distance_by_species={"Li": 1.6},
        symmetry_deduplicate=False,
    )
    assert len(ordered) == len(records) == 2
    assert records[0]["structure_fingerprint"] != records[1]["structure_fingerprint"]
    for item, record in zip(ordered, records):
        composition = {
            str(element): round(amount)
            for element, amount in item.composition.get_el_amt_dict().items()
        }
        assert composition == target
        assert record["minimum_distance_by_species"]["Li"] >= 1.6


def test_noninteger_target_is_rejected():
    structure, _warnings = _load_disordered(
        ROOT / "data/structures/raw/cod_1545083.cif"
    )
    with pytest.raises(ValueError, match="integer-valued"):
        enumerate_exact_orderings(
            structure,
            {"Li": 51.5, "La": 24, "Zr": 12, "Ta": 4, "O": 96},
            max_solutions=1,
        )


def test_frozen_protocol_is_doubly_disabled():
    protocol = load_ordering_protocol(PROTOCOL)
    assert not protocol.enabled
    assert protocol.approved_candidate_ids == ()
    with pytest.raises(RuntimeError, match="disabled"):
        run_ordering_campaign(PROTOCOL)


def test_duplicate_approval_is_rejected(tmp_path):
    payload = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    payload["approved_candidate_ids"] = ["cod-1", "cod-1"]
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicates"):
        load_ordering_protocol(path)
