from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.velocity_statistics import (  # noqa: E402
    analyze_balanced_records,
    fit_nested_reml,
    infer_nested_velocity,
    paired_log_ratio_variance,
)


def _nested_values(with_occupancy_effect: bool = True):
    values = []
    variances = []
    groups = []
    occupancy_effects = [-0.6, -0.3, 0.0, 0.3, 0.6]
    velocity_effects = [-0.04, 0.01, 0.03]
    for occupancy, effect in enumerate(occupancy_effects):
        for velocity in velocity_effects:
            values.append(-11.0 + (effect if with_occupancy_effect else 0.0) + velocity)
            variances.append(0.02**2)
            groups.append(occupancy)
    return values, variances, groups


def test_nested_reml_separates_large_occupancy_from_velocity_variation():
    values, variances, groups = _nested_values()
    result = fit_nested_reml(values, variances, groups)
    assert result["occupancy_variance_log_scale"] > 0.05
    assert result["occupancy_variance_log_scale"] > result["velocity_variance_log_scale"]
    assert result["n_observations"] == 15
    assert result["n_occupancies"] == 5


def test_nested_reml_keeps_no_occupancy_effect_on_the_exact_boundary():
    values, variances, groups = _nested_values(with_occupancy_effect=False)
    result = fit_nested_reml(values, variances, groups)
    assert result["occupancy_variance_log_scale"] == 0.0
    assert result["occupancy_sd_log_scale"] == 0.0


def test_boundary_bootstrap_detects_a_planted_occupancy_effect():
    values, variances, groups = _nested_values()
    result = infer_nested_velocity(
        values,
        variances,
        groups,
        confidence_level=0.95,
        null_iterations=100,
        null_seed=17,
        interval_iterations=100,
        interval_seed=19,
        interval_quantiles=[0.025, 0.5, 0.975],
        alpha=0.05,
    )
    test = result["occupancy_variance_boundary_test"]
    assert test["p_value"] <= 0.05
    assert test["occupancy_variance_supported"] is True


def test_paired_ratio_uncertainty_uses_explicit_block_covariance():
    tracer = [1.0e-6, 1.2e-6, 0.9e-6, 1.4e-6, 1.1e-6]
    multipliers = [1.8, 2.1, 1.9, 2.3, 2.0]
    rows = [
        {
            "block_index": index,
            "tracer_diffusivity_cm2_s": value,
            "collective_diffusivity_cm2_s": value * multipliers[index],
        }
        for index, value in enumerate(tracer)
    ]
    result = paired_log_ratio_variance(
        {"block_estimates": rows},
        expected_blocks=5,
        minimum_blocks=4,
    )
    expected = sum(
        (math.log(value) - sum(map(math.log, multipliers)) / 5) ** 2
        for value in multipliers
    ) / 4 / 5
    assert result["variance_log_ratio"] == pytest.approx(expected)
    assert result["pairing_method"] == "explicit_block_indices"
    assert result["block_indices"] == list(range(5))


def test_legacy_ratio_pairing_requires_every_declared_block():
    transport = {
        "tracer": {"block_diffusivities_cm2_s": [1.0, 1.2, 0.9, 1.4, 1.1]},
        "collective": {"block_diffusivities_cm2_s": [1.8, 2.52, 1.71, 3.22, 2.2]},
    }
    result = paired_log_ratio_variance(
        transport,
        expected_blocks=5,
        minimum_blocks=4,
    )
    assert result["pairing_method"] == "legacy_complete_block_order"
    transport["collective"]["block_diffusivities_cm2_s"].pop()
    with pytest.raises(ValueError, match="paired positive"):
        paired_log_ratio_variance(
            transport,
            expected_blocks=5,
            minimum_blocks=4,
        )


def test_balanced_grid_is_a_hard_requirement_before_any_fit():
    values, variances, groups = _nested_values()
    records = []
    for index, (value, variance, group) in enumerate(
        zip(values, variances, groups)
    ):
        measurement = {
            "log_value": value,
            "variance_log_value": variance,
            "resolved": True,
        }
        records.append(
            {
                "run_id": f"run-{index}",
                "occupancy_seed": group,
                "velocity_seed": 1000 + index,
                "estimators": {
                    "tracer": measurement,
                    "collective": measurement,
                    "collective_to_tracer_ratio": measurement,
                },
            }
        )
    protocol = {
        "sensitivity_roles": {
            "velocity_design": {
                "occupancy_realizations": 5,
                "velocity_initializations_per_occupancy": 3,
            }
        },
        "nested_velocity_inference": {},
    }
    records.pop()
    with pytest.raises(ValueError, match="not balanced"):
        analyze_balanced_records(records, protocol)
