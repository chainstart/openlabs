"""Tests for the diffusivity and Arrhenius numerics.

These use synthetic trajectories with known answers, so a regression in the
physics pipeline is caught without spending GPU hours. The MD driver itself is
not tested here: it needs a GPU and a downloaded potential.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.mlipmd import (  # noqa: E402
    K_B_EV,
    MDConfig,
    DiffusionPoint,
    _model_metadata,
    _prepare_manifest,
    diffusivity_from_msd,
    fit_arrhenius,
    linear_fit,
    mean_squared_displacement,
    unwrap_trajectory,
)


def _point(temperature: int, diffusivity: float) -> DiffusionPoint:
    return DiffusionPoint(
        temperature=temperature,
        diffusivity_cm2_s=diffusivity,
        msd_slope_a2_ps=diffusivity * 6e4,
        fit_r2=0.999,
        n_frames=500,
        production_ps=50.0,
        n_mobile=28,
        wall_seconds=1.0,
    )


class TestLinearFit:
    def test_exact_line(self):
        slope, intercept, r2, _ = linear_fit([0, 1, 2, 3], [1, 3, 5, 7])
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(1.0)
        assert r2 == pytest.approx(1.0)

    def test_stderr_is_zero_for_perfect_fit(self):
        _, _, _, stderr = linear_fit([0, 1, 2, 3], [0, 2, 4, 6])
        assert stderr == pytest.approx(0.0, abs=1e-12)

    def test_two_points_have_no_estimable_error(self):
        _, _, _, stderr = linear_fit([0, 1], [0, 1])
        assert math.isnan(stderr)

    def test_vertical_input_is_rejected(self):
        with pytest.raises(ValueError):
            linear_fit([1, 1, 1], [0, 1, 2])

    def test_single_point_is_rejected(self):
        with pytest.raises(ValueError):
            linear_fit([1], [1])


class TestMSD:
    def test_uniform_translation_is_removed_as_drift(self):
        # Mobile ions and a distinct host framework move together: rigid drift.
        frames = [[[t, 0, 0], [t, 1, 0]] for t in range(10)]
        framework = [[[t, 2, 0], [t, 3, 0], [t, 4, 0]] for t in range(10)]
        msd = mean_squared_displacement(frames, framework_positions=framework)
        assert max(msd) == pytest.approx(0.0, abs=1e-12)

    def test_drift_retained_when_correction_disabled(self):
        frames = [[[t, 0, 0], [t, 1, 0]] for t in range(10)]
        msd = mean_squared_displacement(frames, remove_drift=False)
        assert msd[-1] == pytest.approx(81.0)

    def test_opposed_motion_is_real_displacement(self):
        # Li motion relative to a stationary host framework is real transport.
        frames = [[[t, 0, 0], [-t, 0, 0]] for t in range(5)]
        framework = [[[0, 1, 0], [0, -1, 0]] for _ in range(5)]
        msd = mean_squared_displacement(frames, framework_positions=framework)
        assert msd[-1] == pytest.approx(16.0)

    def test_first_frame_is_the_origin(self):
        frames = [[[5, 5, 5], [-5, -5, -5]] for _ in range(3)]
        framework = [[[0, 0, 0]] for _ in range(3)]
        msd = mean_squared_displacement(frames, framework_positions=framework)
        assert msd[0] == pytest.approx(0.0)

    def test_mobile_framework_is_required_for_drift_correction(self):
        with pytest.raises(ValueError, match="framework_positions"):
            mean_squared_displacement([[[0, 0, 0]], [[1, 0, 0]]])

    def test_concerted_mobile_motion_is_not_erased(self):
        mobile = [[[t, 0, 0], [t, 1, 0]] for t in range(5)]
        framework = [[[0, 2, 0], [0, 3, 0]] for _ in range(5)]
        msd = mean_squared_displacement(mobile, framework_positions=framework)
        assert msd[-1] == pytest.approx(16.0)

    def test_wrong_shape_is_rejected(self):
        with pytest.raises(ValueError):
            mean_squared_displacement([[1, 2, 3], [4, 5, 6]])


class _Frame:
    def __init__(self, fractional):
        self.fractional = fractional

    def get_cell(self):
        return [[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]]

    def get_scaled_positions(self, *, wrap=True):
        assert wrap
        return self.fractional


def test_periodic_boundary_crossing_is_unwrapped_continuously():
    frames = [
        _Frame([[0.90, 0.2, 0.3]]),
        _Frame([[0.97, 0.2, 0.3]]),
        _Frame([[0.04, 0.2, 0.3]]),
        _Frame([[0.11, 0.2, 0.3]]),
    ]
    positions = unwrap_trajectory(frames)
    assert positions[:, 0, 0].tolist() == pytest.approx([9.0, 9.7, 10.4, 11.1])


def test_run_manifest_refuses_changed_protocol(tmp_path):
    metadata = {"prepared_structure_sha256": "structure-a"}
    first = MDConfig(temperatures=(700, 800, 900), production_steps=100)
    _manifest, first_fingerprint = _prepare_manifest(first, metadata, tmp_path)
    _same_manifest, same_fingerprint = _prepare_manifest(first, metadata, tmp_path)
    assert same_fingerprint == first_fingerprint

    changed = MDConfig(temperatures=(700, 800, 900), production_steps=101)
    with pytest.raises(RuntimeError, match="protocol mismatch"):
        _prepare_manifest(changed, metadata, tmp_path)


def test_single_temperature_is_allowed_for_convergence_studies():
    MDConfig(temperatures=(800,)).validate()


def test_model_weight_hash_is_stable_and_sensitive():
    torch = pytest.importorskip("torch")

    class FakeModel:
        def __init__(self, value):
            self.value = value

        def state_dict(self):
            return {
                "z": torch.tensor([self.value], dtype=torch.float32),
                "a": torch.tensor([[1, 2]], dtype=torch.int64),
            }

    first = _model_metadata(FakeModel(1.0), "test")
    same = _model_metadata(FakeModel(1.0), "test")
    changed = _model_metadata(FakeModel(2.0), "test")
    assert first["state_dict_sha256"] == same["state_dict_sha256"]
    assert first["state_dict_sha256"] != changed["state_dict_sha256"]
    assert first["n_parameters"] == 3


class TestDiffusivity:
    def test_known_slope_recovers_einstein_relation(self):
        # MSD = 6 A^2/ps * t means D = 1 A^2/ps = 1e-4 cm^2/s.
        times = [i * 0.1 for i in range(100)]
        msd = [6.0 * t for t in times]
        diffusivity, slope, r2 = diffusivity_from_msd(msd, times)
        assert slope == pytest.approx(6.0)
        assert diffusivity == pytest.approx(1e-4)
        assert r2 == pytest.approx(1.0)

    def test_ballistic_onset_is_excluded_from_the_fit(self):
        # Quadratic for the first 20%, then linear: fitting the whole curve
        # would overestimate the slope.
        times = [i * 0.1 for i in range(100)]
        msd = [(t * t if i < 20 else 6.0 * t) for i, t in enumerate(times)]
        _, slope, r2 = diffusivity_from_msd(msd, times)
        assert slope == pytest.approx(6.0)
        assert r2 == pytest.approx(1.0)

    def test_mismatched_lengths_are_rejected(self):
        with pytest.raises(ValueError):
            diffusivity_from_msd([1.0, 2.0], [0.1])

    def test_too_few_frames_are_rejected(self):
        with pytest.raises(ValueError):
            diffusivity_from_msd([1.0, 2.0, 3.0], [0.1, 0.2, 0.3], fit_from=0.9, fit_to=0.91)


class TestArrhenius:
    def test_recovers_a_planted_activation_energy(self):
        planted_ea = 0.35
        prefactor = 2.5e-3
        temperatures = [600, 700, 800, 900, 1000, 1200]
        points = [
            _point(t, prefactor * math.exp(-planted_ea / (K_B_EV * t)))
            for t in temperatures
        ]
        fit = fit_arrhenius(points)
        assert fit.activation_energy_ev == pytest.approx(planted_ea, abs=1e-9)
        assert fit.prefactor_cm2_s == pytest.approx(prefactor, rel=1e-6)
        assert fit.r2 == pytest.approx(1.0)
        assert fit.temperature_range_k == (600, 1200)

    def test_zero_diffusivity_points_are_not_silently_dropped(self):
        points = [_point(t, 0.0) for t in (600, 700)]
        points += [
            _point(t, 1e-3 * math.exp(-0.3 / (K_B_EV * t))) for t in (800, 900, 1000)
        ]
        with pytest.raises(ValueError, match="non-positive"):
            fit_arrhenius(points)

    def test_unresolved_temperature_blocks_arrhenius_fit(self):
        points = [
            _point(t, 1e-3 * math.exp(-0.3 / (K_B_EV * t)))
            for t in (700, 800, 900)
        ]
        points[0].resolved = False
        with pytest.raises(ValueError, match="extend"):
            fit_arrhenius(points)

    def test_too_few_usable_points_is_an_error(self):
        points = [_point(600, 1e-8), _point(700, 1e-7)]
        with pytest.raises(ValueError, match="at least three"):
            fit_arrhenius(points)

    def test_all_dead_points_is_an_error(self):
        with pytest.raises(ValueError):
            fit_arrhenius([_point(t, 0.0) for t in (600, 700, 800, 900)])

    def test_noise_lowers_r2_and_raises_stderr(self):
        clean = [_point(t, 1e-3 * math.exp(-0.3 / (K_B_EV * t))) for t in (600, 700, 800, 900, 1000)]
        noisy = list(clean)
        noisy[2] = _point(800, clean[2].diffusivity_cm2_s * 3.0)
        clean_fit, noisy_fit = fit_arrhenius(clean), fit_arrhenius(noisy)
        assert noisy_fit.r2 < clean_fit.r2
        assert noisy_fit.activation_energy_stderr_ev > clean_fit.activation_energy_stderr_ev
