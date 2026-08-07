from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.mlipmd import K_B_EV  # noqa: E402
from matfactory.transport_statistics import (  # noqa: E402
    analyze_hierarchical_estimator,
    reml_random_effects_meta,
)


def _records() -> list[dict]:
    records = []
    temperatures = [700, 750, 800, 850, 900]
    for group_index, energy in enumerate((0.33, 0.34, 0.35, 0.36, 0.37)):
        prefactor = 2e-3 * math.exp(0.03 * group_index)
        for temperature in temperatures:
            diffusion = prefactor * math.exp(-energy / (K_B_EV * temperature))
            records.append(
                {
                    "group_id": f"occ{group_index}",
                    "temperature_k": temperature,
                    "diffusivity_cm2_s": diffusion,
                    "stderr_cm2_s": 0.02 * diffusion,
                    "resolved": True,
                    "n_mobile": 26,
                    "volume_angstrom3": 1100.0 + group_index,
                }
            )
    return records


def test_hierarchical_analysis_uses_configurations_and_recovers_mean_energy():
    report = analyze_hierarchical_estimator(
        _records(),
        required_temperatures_k=[700, 750, 800, 850, 900],
        bootstrap_iterations=200,
        bootstrap_seed=17,
        bootstrap_quantiles=[0.025, 0.5, 0.975],
        room_temperature_k=300,
        confidence_level=0.95,
        curvature_aicc_improvement_min=6.0,
        prediction_temperatures_k=[298.0, 333.0],
        compute_nernst_einstein_conductivity=True,
    )
    assert report["n_configurations"] == 5
    assert report["activation_energy_random_effects"]["mean"] == pytest.approx(
        0.35, abs=0.02
    )
    assert report["nested_configuration_bootstrap"]["activation_energy_ev"][
        "mean"
    ] == pytest.approx(0.35, abs=0.02)
    assert report["non_arrhenius_diagnostic"]["non_arrhenius_supported"] is False
    predictions = report["nested_configuration_bootstrap"]["temperature_predictions"]
    assert set(predictions) == {"298", "300", "333"}
    assert predictions["298"]["is_extrapolation"] is True
    assert (
        predictions["298"]["new_configuration_predictive"]
        ["conductivity_s_cm_quantiles"]["0.5"]
        > 0
    )


def test_incomplete_or_unresolved_grid_is_not_silently_reduced():
    records = _records()
    records.pop()
    with pytest.raises(ValueError, match="complete grid"):
        analyze_hierarchical_estimator(
            records,
            required_temperatures_k=[700, 750, 800, 850, 900],
            bootstrap_iterations=100,
            bootstrap_seed=1,
            bootstrap_quantiles=[0.025, 0.5, 0.975],
            room_temperature_k=300,
            confidence_level=0.95,
            curvature_aicc_improvement_min=6.0,
        )

    records = _records()
    records[0]["resolved"] = False
    with pytest.raises(ValueError, match="unresolved"):
        analyze_hierarchical_estimator(
            records,
            required_temperatures_k=[700, 750, 800, 850, 900],
            bootstrap_iterations=100,
            bootstrap_seed=1,
            bootstrap_quantiles=[0.025, 0.5, 0.975],
            room_temperature_k=300,
            confidence_level=0.95,
            curvature_aicc_improvement_min=6.0,
        )


def test_reml_meta_reports_between_configuration_uncertainty():
    report = reml_random_effects_meta(
        [0.30, 0.35, 0.40, 0.45, 0.50],
        [0.01**2] * 5,
        confidence_level=0.95,
    )
    assert report["mean"] == pytest.approx(0.40, abs=1e-5)
    assert report["between_configuration_sd_tau"] > 0.05
    assert report["prediction_interval"][0] < report["confidence_interval"][0]


def test_reml_meta_retains_the_exact_zero_heterogeneity_boundary():
    report = reml_random_effects_meta(
        [0.4] * 5,
        [0.01**2] * 5,
        confidence_level=0.95,
    )
    assert report["between_configuration_variance_tau2"] == 0.0
    assert report["between_configuration_sd_tau"] == 0.0
    assert report["i2_fraction"] == 0.0


@pytest.mark.parametrize("confidence_level", [0.0, 1.0, -0.1, 1.1])
def test_reml_meta_rejects_invalid_confidence_levels(confidence_level):
    with pytest.raises(ValueError, match="confidence_level"):
        reml_random_effects_meta(
            [0.3, 0.4, 0.5],
            [0.01**2] * 3,
            confidence_level=confidence_level,
        )
