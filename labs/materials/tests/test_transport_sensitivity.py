from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign  # noqa: E402
from matfactory.transport_sensitivity import (  # noqa: E402
    bootstrap_log_effect,
    estimator_block_logs,
)


def _point():
    return {
        "resolved": True,
        "collective_resolved": True,
        "diffusivity_cm2_s": 1.0e-6,
        "collective_diffusivity_cm2_s": 2.0e-6,
        "collective_to_tracer_ratio": 2.0,
    }


def _transport():
    tracer = [0.8e-6, 1.0e-6, 1.1e-6, 0.9e-6, 1.2e-6]
    ratios = [1.8, 2.0, 2.2, 1.9, 2.1]
    return {
        "transport": {
            "block_estimates": [
                {
                    "block_index": index,
                    "tracer_diffusivity_cm2_s": value,
                    "collective_diffusivity_cm2_s": value * ratios[index],
                }
                for index, value in enumerate(tracer)
            ]
        }
    }


@pytest.mark.parametrize(
    "estimator,central",
    [
        ("tracer", 1.0e-6),
        ("collective", 2.0e-6),
        ("collective_to_tracer_ratio", 2.0),
    ],
)
def test_block_extractors_keep_explicit_pairing(estimator, central):
    result = estimator_block_logs(
        _point(),
        _transport(),
        estimator,
        expected_blocks=5,
        minimum_blocks=4,
    )
    assert result["central_value"] == pytest.approx(central)
    assert result["block_indices"] == list(range(5))
    assert result["block_method"] == "explicit_block_indices"
    assert len(result["block_log_values"]) == 5


def test_unresolved_estimator_is_not_compared():
    point = _point()
    point["collective_resolved"] = False
    with pytest.raises(ValueError, match="unresolved"):
        estimator_block_logs(
            point,
            _transport(),
            "collective",
            expected_blocks=5,
            minimum_blocks=4,
        )


def test_centered_block_bootstrap_applies_an_equivalence_margin():
    reference = {
        "central_log_value": math.log(1.0),
        "block_log_values": [math.log(value) for value in (0.9, 1.0, 1.1, 1.0, 1.05)],
        "n_blocks": 5,
        "block_indices": list(range(5)),
        "block_method": "test",
    }
    comparison = {
        "central_log_value": math.log(1.2),
        "block_log_values": [math.log(value) for value in (1.1, 1.2, 1.3, 1.2, 1.25)],
        "n_blocks": 5,
        "block_indices": list(range(5)),
        "block_method": "test",
    }
    broad = bootstrap_log_effect(
        reference,
        comparison,
        iterations=500,
        seed=11,
        quantiles=[0.025, 0.5, 0.975],
        equivalence_ratio_margin=2.0,
    )
    narrow = bootstrap_log_effect(
        reference,
        comparison,
        iterations=500,
        seed=11,
        quantiles=[0.025, 0.5, 0.975],
        equivalence_ratio_margin=1.05,
    )
    assert broad["central_ratio"] == pytest.approx(1.2)
    assert broad["equivalence_supported"] is True
    assert narrow["equivalence_supported"] is False


def test_fixed_volume_replacement_matches_primary_md_duration():
    formal = load_campaign(ROOT / "protocols/llzto_q1_v1.json")
    replacement = load_campaign(
        ROOT / "protocols/llzto_volume_fixed_matched_v1.json"
    )
    primary = next(run for run in formal.runs if run.run_id == "formal-occ00-vel1701")
    control = replacement.runs[0]
    assert control.config.equilibration_steps == primary.config.equilibration_steps
    assert control.config.production_steps == primary.config.production_steps
    assert control.config.loginterval == primary.config.loginterval
    assert control.config.occupancy_seed == primary.config.occupancy_seed
    assert control.config.seed == primary.config.seed
    assert control.config.relax_cell is False
    assert primary.config.relax_cell is True
