"""Transport estimators with explicit drift, convergence, and uncertainty checks."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MSDCurve:
    """Time-origin averaged tracer and collective MSD curves."""

    times_ps: list[float]
    lag_frames: list[int]
    tracer_msd_a2: list[float]
    collective_msd_a2: list[float]
    n_time_origins: list[int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiffusionFit:
    """One Einstein-slope estimate and diagnostics for the fitted regime."""

    diffusivity_cm2_s: float
    diffusivity_stderr_cm2_s: float | None
    slope_a2_ps: float
    intercept_a2: float
    r2: float
    diffusive_exponent: float | None
    fit_start_ps: float
    fit_end_ps: float
    n_fit_lags: int
    block_diffusivities_cm2_s: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TransportEstimate:
    """Tracer/collective transport plus an auditable adequacy decision."""

    tracer: DiffusionFit
    collective: DiffusionFit
    collective_to_tracer_ratio: float | None
    resolved: bool
    rejection_reasons: list[str]
    collective_resolved: bool
    collective_rejection_reasons: list[str]
    final_tracer_msd_a2: float
    final_collective_msd_a2: float
    curve: MSDCurve
    block_estimates: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_positions(mobile: Any, framework: Any) -> tuple[Any, Any]:
    import numpy as np

    mobile_array = np.asarray(mobile, dtype=float)
    framework_array = np.asarray(framework, dtype=float)
    if mobile_array.ndim != 3 or mobile_array.shape[-1] != 3:
        raise ValueError("mobile positions must have shape (frames, atoms, 3)")
    if framework_array.ndim != 3 or framework_array.shape[-1] != 3:
        raise ValueError("framework positions must have shape (frames, atoms, 3)")
    if mobile_array.shape[0] != framework_array.shape[0]:
        raise ValueError("mobile and framework trajectories need the same frame count")
    if mobile_array.shape[0] < 4:
        raise ValueError("at least four trajectory frames are required")
    if mobile_array.shape[1] == 0 or framework_array.shape[1] == 0:
        raise ValueError("mobile and framework selections must both be non-empty")
    return mobile_array, framework_array


def time_origin_averaged_msd(
    mobile_positions: Any,
    framework_positions: Any,
    *,
    frame_ps: float,
    framework_weights: Any | None = None,
    max_lag_fraction: float = 0.5,
    max_lags: int = 500,
) -> MSDCurve:
    """Tracer and collective MSD using all available origins at each lag.

    Translation is estimated from the non-mobile host framework and subtracted
    from every mobile-ion displacement. The mobile-sublattice mean is never
    subtracted: concerted Li motion is real transport and must remain in both
    the tracer and collective estimators.
    """
    import numpy as np

    mobile, framework = _validate_positions(mobile_positions, framework_positions)
    if frame_ps <= 0:
        raise ValueError("frame_ps must be positive")
    if not 0 < max_lag_fraction < 1:
        raise ValueError("max_lag_fraction must be between zero and one")
    if max_lags < 2:
        raise ValueError("max_lags must be at least two")

    weights = None
    if framework_weights is not None:
        weights = np.asarray(framework_weights, dtype=float)
        if weights.shape != (framework.shape[1],):
            raise ValueError("framework_weights must have one value per framework atom")
        if not np.all(np.isfinite(weights)) or np.any(weights <= 0):
            raise ValueError("framework_weights must be finite and positive")

    maximum = max(2, int((mobile.shape[0] - 1) * max_lag_fraction))
    maximum = min(maximum, mobile.shape[0] - 1)
    count = min(maximum, max_lags)
    lags = np.unique(np.rint(np.linspace(1, maximum, count)).astype(int))

    tracer: list[float] = []
    collective: list[float] = []
    origins: list[int] = []
    n_mobile = mobile.shape[1]
    for lag in lags:
        mobile_delta = mobile[lag:] - mobile[:-lag]
        framework_delta = framework[lag:] - framework[:-lag]
        drift = np.average(framework_delta, axis=1, weights=weights)
        corrected = mobile_delta - drift[:, None, :]
        tracer.append(float(np.mean(np.sum(corrected * corrected, axis=2))))
        summed = np.sum(corrected, axis=1)
        collective.append(float(np.mean(np.sum(summed * summed, axis=1)) / n_mobile))
        origins.append(int(corrected.shape[0]))

    return MSDCurve(
        times_ps=[float(lag * frame_ps) for lag in lags],
        lag_frames=[int(lag) for lag in lags],
        tracer_msd_a2=tracer,
        collective_msd_a2=collective,
        n_time_origins=origins,
    )


def _weighted_line(x: Any, y: Any, weights: Any) -> tuple[float, float, float]:
    import numpy as np

    design = np.column_stack([x, np.ones_like(x)])
    root_weight = np.sqrt(weights)
    coefficients, *_ = np.linalg.lstsq(
        design * root_weight[:, None], y * root_weight, rcond=None
    )
    slope, intercept = (float(value) for value in coefficients)
    prediction = slope * x + intercept
    mean = float(np.average(y, weights=weights))
    residual = float(np.sum(weights * (y - prediction) ** 2))
    total = float(np.sum(weights * (y - mean) ** 2))
    r2 = 1.0 - residual / total if total > 0 else 0.0
    return slope, intercept, r2


def fit_msd_curve(
    times_ps: Any,
    msd_a2: Any,
    n_time_origins: Any,
    *,
    fit_from_fraction: float = 0.2,
    fit_to_fraction: float = 0.8,
) -> DiffusionFit:
    """Fit an Einstein slope and log-log exponent over an explicit lag window."""
    import numpy as np

    times = np.asarray(times_ps, dtype=float)
    msd = np.asarray(msd_a2, dtype=float)
    origins = np.asarray(n_time_origins, dtype=float)
    if not (times.ndim == msd.ndim == origins.ndim == 1):
        raise ValueError("times, MSD, and origin counts must be one-dimensional")
    if not (times.size == msd.size == origins.size):
        raise ValueError("times, MSD, and origin counts must have equal lengths")
    if times.size < 4:
        raise ValueError("at least four MSD lags are required")
    if not 0 <= fit_from_fraction < fit_to_fraction <= 1:
        raise ValueError("fit fractions must satisfy 0 <= from < to <= 1")

    start_time = times[-1] * fit_from_fraction
    end_time = times[-1] * fit_to_fraction
    mask = (
        (times >= start_time)
        & (times <= end_time)
        & np.isfinite(msd)
        & (origins > 0)
    )
    if np.count_nonzero(mask) < 4:
        raise ValueError("fit window contains fewer than four valid lags")
    x = times[mask]
    y = msd[mask]
    weights = origins[mask] / origins[mask].max()
    slope, intercept, r2 = _weighted_line(x, y, weights)

    positive = y > 0
    if np.count_nonzero(positive) < 4:
        exponent = None
    else:
        exponent_value, _log_intercept, _log_r2 = _weighted_line(
            np.log(x[positive]), np.log(y[positive]), weights[positive]
        )
        exponent = exponent_value
    return DiffusionFit(
        diffusivity_cm2_s=slope / 6.0 * 1e-4,
        diffusivity_stderr_cm2_s=None,
        slope_a2_ps=slope,
        intercept_a2=intercept,
        r2=r2,
        diffusive_exponent=exponent,
        fit_start_ps=float(x[0]),
        fit_end_ps=float(x[-1]),
        n_fit_lags=int(x.size),
    )


def _paired_block_diffusivities(
    mobile: Any,
    framework: Any,
    *,
    frame_ps: float,
    framework_weights: Any | None,
    n_blocks: int,
    max_lags: int,
    fit_from_fraction: float,
    fit_to_fraction: float,
) -> tuple[list[float], list[float], list[dict[str, Any]]]:
    """Fit tracer and collective transport on the same non-overlapping blocks."""
    import numpy as np

    frame_indices = np.array_split(np.arange(mobile.shape[0]), n_blocks)
    tracer_estimates: list[float] = []
    collective_estimates: list[float] = []
    records: list[dict[str, Any]] = []
    for block_index, indices in enumerate(frame_indices):
        if indices.size < 12:
            records.append(
                {
                    "block_index": block_index,
                    "start_frame": int(indices[0]) if indices.size else None,
                    "stop_frame_exclusive": (
                        int(indices[-1] + 1) if indices.size else None
                    ),
                    "n_frames": int(indices.size),
                    "tracer_diffusivity_cm2_s": None,
                    "collective_diffusivity_cm2_s": None,
                    "tracer_fit_error": "fewer than 12 frames",
                    "collective_fit_error": "fewer than 12 frames",
                }
            )
            continue
        curve = time_origin_averaged_msd(
            mobile[indices],
            framework[indices],
            frame_ps=frame_ps,
            framework_weights=framework_weights,
            max_lags=max_lags,
        )
        record: dict[str, Any] = {
            "block_index": block_index,
            "start_frame": int(indices[0]),
            "stop_frame_exclusive": int(indices[-1] + 1),
            "n_frames": int(indices.size),
        }
        for label, values, accepted in (
            ("tracer", curve.tracer_msd_a2, tracer_estimates),
            ("collective", curve.collective_msd_a2, collective_estimates),
        ):
            try:
                fit = fit_msd_curve(
                    curve.times_ps,
                    values,
                    curve.n_time_origins,
                    fit_from_fraction=fit_from_fraction,
                    fit_to_fraction=fit_to_fraction,
                )
            except ValueError as exc:
                record[f"{label}_diffusivity_cm2_s"] = None
                record[f"{label}_fit_error"] = f"{type(exc).__name__}: {exc}"
                continue
            value = float(fit.diffusivity_cm2_s)
            record[f"{label}_diffusivity_cm2_s"] = value
            record[f"{label}_fit_error"] = None
            if math.isfinite(value) and value > 0:
                accepted.append(value)
        records.append(record)
    return tracer_estimates, collective_estimates, records


def estimate_transport(
    mobile_positions: Any,
    framework_positions: Any,
    *,
    frame_ps: float,
    framework_weights: Any | None = None,
    n_blocks: int = 5,
    max_lags: int = 500,
    fit_from_fraction: float = 0.2,
    fit_to_fraction: float = 0.8,
    min_final_msd_a2: float = 20.0,
    alpha_range: tuple[float, float] = (0.8, 1.2),
    max_relative_stderr: float = 0.5,
) -> TransportEstimate:
    """Estimate transport and state whether the trajectory resolves diffusion."""
    import numpy as np

    mobile, framework = _validate_positions(mobile_positions, framework_positions)
    if n_blocks < 2:
        raise ValueError("n_blocks must be at least two")
    curve = time_origin_averaged_msd(
        mobile,
        framework,
        frame_ps=frame_ps,
        framework_weights=framework_weights,
        max_lags=max_lags,
    )
    tracer = fit_msd_curve(
        curve.times_ps,
        curve.tracer_msd_a2,
        curve.n_time_origins,
        fit_from_fraction=fit_from_fraction,
        fit_to_fraction=fit_to_fraction,
    )
    collective = fit_msd_curve(
        curve.times_ps,
        curve.collective_msd_a2,
        curve.n_time_origins,
        fit_from_fraction=fit_from_fraction,
        fit_to_fraction=fit_to_fraction,
    )
    tracer_blocks, collective_blocks, block_records = _paired_block_diffusivities(
        mobile,
        framework,
        frame_ps=frame_ps,
        framework_weights=framework_weights,
        n_blocks=n_blocks,
        max_lags=max_lags,
        fit_from_fraction=fit_from_fraction,
        fit_to_fraction=fit_to_fraction,
    )

    def attach_uncertainty(fit: DiffusionFit, blocks: list[float]) -> None:
        fit.block_diffusivities_cm2_s = [float(value) for value in blocks]
        if len(blocks) >= 2:
            fit.diffusivity_stderr_cm2_s = float(
                np.std(blocks, ddof=1) / math.sqrt(len(blocks))
            )

    attach_uncertainty(tracer, tracer_blocks)
    attach_uncertainty(collective, collective_blocks)

    def adequacy(
        fit: DiffusionFit,
        blocks: list[float],
        final_msd: float,
        *,
        label: str,
    ) -> list[str]:
        reasons: list[str] = []
        if fit.diffusivity_cm2_s <= 0 or not math.isfinite(fit.diffusivity_cm2_s):
            reasons.append(f"non_positive_{label}_diffusivity")
        if (
            fit.diffusive_exponent is None
            or not math.isfinite(fit.diffusive_exponent)
            or not (alpha_range[0] <= fit.diffusive_exponent <= alpha_range[1])
        ):
            reasons.append(f"non_diffusive_{label}_log_log_exponent")
        if final_msd < min_final_msd_a2:
            reasons.append(f"insufficient_{label}_displacement")
        if len(blocks) < max(2, n_blocks - 1):
            reasons.append(f"insufficient_valid_{label}_blocks")
        if fit.diffusivity_stderr_cm2_s is None:
            reasons.append(f"{label}_diffusivity_uncertainty_unavailable")
        elif fit.diffusivity_cm2_s > 0 and (
            fit.diffusivity_stderr_cm2_s / fit.diffusivity_cm2_s
            > max_relative_stderr
        ):
            reasons.append(f"{label}_diffusivity_relative_uncertainty_too_large")
        return reasons

    final_tracer_msd = float(curve.tracer_msd_a2[-1])
    final_collective_msd = float(curve.collective_msd_a2[-1])
    tracer_reasons = adequacy(
        tracer, tracer_blocks, final_tracer_msd, label="tracer"
    )
    collective_reasons = adequacy(
        collective, collective_blocks, final_collective_msd, label="collective"
    )

    ratio = None
    if tracer.diffusivity_cm2_s > 0 and collective.diffusivity_cm2_s > 0:
        ratio = collective.diffusivity_cm2_s / tracer.diffusivity_cm2_s
    return TransportEstimate(
        tracer=tracer,
        collective=collective,
        collective_to_tracer_ratio=ratio,
        resolved=not tracer_reasons,
        rejection_reasons=tracer_reasons,
        collective_resolved=not collective_reasons,
        collective_rejection_reasons=collective_reasons,
        final_tracer_msd_a2=final_tracer_msd,
        final_collective_msd_a2=final_collective_msd,
        curve=curve,
        block_estimates=block_records,
    )
