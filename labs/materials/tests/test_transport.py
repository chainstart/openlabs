"""Synthetic checks for the physically critical transport estimators."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from matfactory.transport import (  # noqa: E402
    estimate_transport,
    fit_msd_curve,
    time_origin_averaged_msd,
)


def _brownian(seed=0, frames=500, mobile_atoms=80, framework_atoms=40, d_a2_ps=0.5):
    rng = np.random.default_rng(seed)
    dt = 0.1
    mobile_steps = rng.normal(
        scale=np.sqrt(2 * d_a2_ps * dt),
        size=(frames - 1, mobile_atoms, 3),
    )
    mobile = np.concatenate(
        [np.zeros((1, mobile_atoms, 3)), np.cumsum(mobile_steps, axis=0)], axis=0
    )
    framework = np.zeros((frames, framework_atoms, 3))
    return mobile, framework, dt


def test_framework_translation_is_removed_but_collective_li_motion_is_retained():
    frames = 30
    drift = np.arange(frames)[:, None, None] * np.array([[[0.2, 0.0, 0.0]]])
    framework = np.repeat(drift, 4, axis=1)
    # Li moves with the framework plus a concerted extra 0.1 A per frame.
    mobile = np.repeat(drift, 3, axis=1)
    mobile[:, :, 0] += np.arange(frames)[:, None] * 0.1
    curve = time_origin_averaged_msd(mobile, framework, frame_ps=0.1)
    assert curve.tracer_msd_a2[-1] > 0
    assert curve.collective_msd_a2[-1] == pytest.approx(
        curve.tracer_msd_a2[-1] * 3
    )


def test_pure_rigid_translation_has_zero_corrected_msd():
    frames = 20
    drift = np.arange(frames)[:, None, None] * np.array([[[0.1, -0.2, 0.3]]])
    mobile = np.repeat(drift, 5, axis=1)
    framework = np.repeat(drift, 8, axis=1)
    curve = time_origin_averaged_msd(mobile, framework, frame_ps=0.1)
    assert max(curve.tracer_msd_a2) == pytest.approx(0.0, abs=1e-12)


def test_brownian_motion_recovers_planted_tracer_diffusivity():
    mobile, framework, dt = _brownian(d_a2_ps=0.5)
    curve = time_origin_averaged_msd(
        mobile, framework, frame_ps=dt, max_lags=200
    )
    fit = fit_msd_curve(curve.times_ps, curve.tracer_msd_a2, curve.n_time_origins)
    # 0.5 A^2/ps = 5e-5 cm^2/s.
    assert fit.diffusivity_cm2_s == pytest.approx(5e-5, rel=0.15)
    assert fit.diffusive_exponent == pytest.approx(1.0, abs=0.15)


def test_estimator_reports_block_uncertainty_and_adequacy():
    mobile, framework, dt = _brownian(frames=700, mobile_atoms=100)
    estimate = estimate_transport(
        mobile,
        framework,
        frame_ps=dt,
        n_blocks=5,
        min_final_msd_a2=1.0,
        max_relative_stderr=1.0,
    )
    assert estimate.tracer.diffusivity_stderr_cm2_s is not None
    assert len(estimate.tracer.block_diffusivities_cm2_s) >= 4
    assert [row["block_index"] for row in estimate.block_estimates] == list(range(5))
    assert all(row["n_frames"] > 0 for row in estimate.block_estimates)
    assert all("tracer_diffusivity_cm2_s" in row for row in estimate.block_estimates)
    assert all("collective_diffusivity_cm2_s" in row for row in estimate.block_estimates)
    assert estimate.resolved
    assert estimate.collective_resolved


def test_short_caged_trajectory_is_explicitly_unresolved():
    rng = np.random.default_rng(5)
    mobile = rng.normal(scale=0.02, size=(80, 20, 3))
    framework = rng.normal(scale=0.01, size=(80, 30, 3))
    estimate = estimate_transport(
        mobile, framework, frame_ps=0.1, n_blocks=4, min_final_msd_a2=20.0
    )
    assert not estimate.resolved
    assert "insufficient_tracer_displacement" in estimate.rejection_reasons
    assert not estimate.collective_resolved
    assert (
        "insufficient_collective_displacement"
        in estimate.collective_rejection_reasons
    )


def test_collective_adequacy_is_not_inherited_from_tracer():
    mobile, framework, dt = _brownian(frames=700, mobile_atoms=100)
    # Remove centre-of-mass motion at every frame. Individual ions still diffuse,
    # while the collective charge displacement is exactly zero.
    mobile -= mobile.mean(axis=1, keepdims=True)
    estimate = estimate_transport(
        mobile,
        framework,
        frame_ps=dt,
        n_blocks=5,
        min_final_msd_a2=1.0,
        max_relative_stderr=1.0,
    )
    assert estimate.resolved
    assert not estimate.collective_resolved
    assert (
        "non_positive_collective_diffusivity"
        in estimate.collective_rejection_reasons
        or "insufficient_collective_displacement"
        in estimate.collective_rejection_reasons
    )
