from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.mechanism_transport import (  # noqa: E402
    _paired_ratio_variance,
    analyze_association_records,
    fit_primary_association,
    holm_adjusted_pvalues,
    publication_analysis_records,
)
from matfactory.mlipmd import K_B_EV  # noqa: E402


def _association_rows() -> list[dict]:
    rows = []
    temperatures = [700, 750, 800, 850, 900]
    descriptor_pattern = np.asarray([-1.4, 0.8, -0.3, 1.5, -0.6])
    for group_index in range(5):
        for temperature_index, temperature in enumerate(temperatures):
            descriptor = float(
                np.roll(descriptor_pattern, group_index)[temperature_index]
                + 0.04 * group_index
            )
            inverse_temperature = 1.0 / (K_B_EV * temperature)
            response = (
                -8.0
                + 0.15 * group_index
                - 0.30 * inverse_temperature
                + 1.25 * descriptor
            )
            rows.append(
                {
                    "group_id": f"occ{group_index}",
                    "temperature_k": temperature,
                    "responses": {
                        "log_tracer_diffusivity": {
                            "value": response,
                            "variance": 0.02**2,
                        }
                    },
                    "primary_descriptors": {"log_jump_rate": descriptor},
                    "descriptor_settings": {
                        "log_jump_rate": {
                            "primary": descriptor,
                            "alternate": 1.15 * descriptor + 0.2,
                        }
                    },
                }
            )
    return rows


def test_holm_adjustment_is_monotone_and_retains_full_family():
    adjusted = holm_adjusted_pvalues({"a": 0.01, "b": 0.03, "c": 0.5})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.06, "c": 0.5})


def test_preregistered_association_requires_all_stability_checks():
    report = analyze_association_records(
        _association_rows(),
        descriptor_names=["log_jump_rate"],
        response_names=["log_tracer_diffusivity"],
        permutation_iterations=399,
        permutation_seed=19,
        bootstrap_iterations=399,
        bootstrap_seed=23,
        bootstrap_quantiles=[0.025, 0.5, 0.975],
        bootstrap_minimum_valid_fraction=0.95,
        alpha=0.05,
    )
    result = report["associations"]["log_tracer_diffusivity"]["log_jump_rate"]
    assert report["grid_gate_pass"] is True
    assert result["primary_fit"]["descriptor_coefficient_per_sample_sd"] > 0
    assert result["permutation_test"]["two_sided_p_value"] <= 0.05
    assert result["cluster_bootstrap"]["interval_excludes_zero"] is True
    assert result["leave_one_occupancy_out"]["sign_stable"] is True
    assert result["mechanism_setting_sensitivity"]["sign_stable"] is True
    assert result["association_supported"] is True
    assert report["causal_mechanism_claim_allowed"] is False


def test_incomplete_grid_is_blocked_instead_of_reduced():
    rows = _association_rows()
    rows.pop()
    report = analyze_association_records(
        rows,
        descriptor_names=["log_jump_rate"],
        response_names=["log_tracer_diffusivity"],
        permutation_iterations=99,
        permutation_seed=1,
        bootstrap_iterations=99,
        bootstrap_seed=2,
        bootstrap_quantiles=[0.025, 0.5, 0.975],
        bootstrap_minimum_valid_fraction=0.95,
        alpha=0.05,
    )
    assert report["grid_gate_pass"] is False
    assert (
        report["associations"]["log_tracer_diffusivity"]["log_jump_rate"][
            "analysis_gate_pass"
        ]
        is False
    )


def test_configuration_constant_descriptor_is_not_identifiable_with_fixed_intercepts():
    groups = np.repeat(np.asarray([f"occ{i}" for i in range(5)], dtype=object), 5)
    temperatures = np.tile(np.asarray([700, 750, 800, 850, 900]), 5)
    descriptor = np.repeat(np.arange(5, dtype=float), 5)
    response = -0.4 / (K_B_EV * temperatures) + descriptor
    with pytest.raises(ValueError, match="rank deficient"):
        fit_primary_association(
            response,
            np.full(25, 0.01),
            temperatures,
            groups,
            descriptor,
        )


def test_legacy_complete_block_lists_preserve_ratio_covariance():
    transport = {
        "tracer": {"block_diffusivities_cm2_s": [1.0, 2.0, 1.5, 2.5, 3.0]},
        "collective": {
            "block_diffusivities_cm2_s": [2.0, 3.0, 2.7, 4.0, 5.1]
        },
    }
    variance, count, mode = _paired_ratio_variance(transport, minimum_blocks=4)
    expected = np.var(
        np.log(np.asarray([2.0, 3.0, 2.7, 4.0, 5.1]))
        - np.log(np.asarray([1.0, 2.0, 1.5, 2.5, 3.0])),
        ddof=1,
    ) / 5
    assert variance == pytest.approx(expected)
    assert count == 5
    assert mode == "legacy_positionally_paired_complete_block_lists"
    assert math.isfinite(variance)


def test_association_records_retain_point_level_values_for_publication_tables():
    source = _association_rows()[0]
    source.update(
        occupancy_seed=0,
        volume_mean_angstrom3=1100.0,
        response_errors={},
        mechanism_qualification={
            "cooperative_string_claim_supported_across_grid": False
        },
    )
    retained = publication_analysis_records([source])
    assert retained[0]["primary_descriptors"]["log_jump_rate"] == pytest.approx(
        -1.4
    )
    assert "descriptor_settings" not in retained[0]
    assert retained[0]["mechanism_qualification"][
        "cooperative_string_claim_supported_across_grid"
    ] is False
