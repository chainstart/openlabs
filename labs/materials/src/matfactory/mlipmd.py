"""Reproducible CHGNet MD transport and activation-energy workflow.

The production path uses an explicitly pinned structure, force/cell relaxation,
clean equilibration and production trajectories, host-framework drift
correction, time-origin averaged MSD, block uncertainty, and strict resume
fingerprints. A numerically completed run is not automatically accepted as a
resolved diffusion measurement; the adequacy decision travels with each point.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .provenance import (
    atomic_write_json,
    atomic_write_text,
    environment_versions,
    file_manifest,
    fingerprint,
    git_state,
    sha256_file,
)
from .transport import estimate_transport

K_B_EV = 8.617333262e-5


@dataclass
class MDConfig:
    """A complete, fingerprinted protocol for one configuration replica."""

    schema_version: str = "2.1"
    protocol_name: str = "llzto-transport-v3"
    protocol_tier: str = "pilot"
    formula: str = "Li6.5La3Zr1.5Ta0.5O12"
    structure_file: str | None = "data/structures/raw/cod_1545083.cif"
    structure_id: str | None = "COD-1545083"
    structure_provider: str = "mp"
    structure_index: int = 0
    occupancy_seed: int = 0
    primitive_cell: bool = True
    min_initial_li_li_distance_angstrom: float = 1.6
    # Legacy ordered-host substitution is screening-only and requires an
    # explicit opt-in. The publication workflow uses the experimental LLZTO CIF.
    dopant: str | None = None
    dopant_count: int = 0
    allow_random_doping: bool = False
    supercell: tuple[int, int, int] = (1, 1, 1)
    temperatures: tuple[int, ...] = (700, 750, 800, 850, 900)
    timestep_fs: float = 2.0
    equilibration_steps: int = 5_000
    production_steps: int = 50_000
    loginterval: int = 50
    equilibration_ensemble: str = "nvt"
    production_ensemble: str = "nvt"
    thermostat: str = "Nose-Hoover"
    thermostat_tau_fs: float = 100.0
    pressure_gpa: float = 0.000101325
    barostat_tau_fs: float = 1_000.0
    relax_structure: bool = True
    relax_cell: bool = True
    relax_fmax_ev_a: float = 0.05
    relax_steps: int = 1_000
    seed: int = 0
    mobile_species: str = "Li"
    fit_from_fraction: float = 0.2
    fit_to_fraction: float = 0.8
    max_lags: int = 500
    uncertainty_blocks: int = 5
    min_final_msd_a2: float = 20.0
    min_diffusive_exponent: float = 0.8
    max_diffusive_exponent: float = 1.2
    max_relative_diffusivity_stderr: float = 0.5
    max_abs_nve_energy_drift_mev_atom_ps: float = 1.0
    device: str = "cuda"
    model_name: str = "CHGNet-default"
    expected_model_state_dict_sha256: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if not self.temperatures or len(set(self.temperatures)) != len(self.temperatures):
            raise ValueError("at least one temperature is required and values must be unique")
        if any(temperature <= 0 for temperature in self.temperatures):
            raise ValueError("temperatures must be positive")
        if self.timestep_fs <= 0 or self.equilibration_steps <= 0 or self.production_steps <= 0:
            raise ValueError("timestep and MD step counts must be positive")
        if self.loginterval <= 0 or self.loginterval > self.production_steps:
            raise ValueError("loginterval must be positive and no larger than production_steps")
        if self.uncertainty_blocks < 2:
            raise ValueError("uncertainty_blocks must be at least two")
        if self.max_lags < 4:
            raise ValueError("max_lags must be at least four")
        if self.min_final_msd_a2 < 0:
            raise ValueError("min_final_msd_a2 cannot be negative")
        if self.max_relative_diffusivity_stderr <= 0:
            raise ValueError("max_relative_diffusivity_stderr must be positive")
        if self.max_abs_nve_energy_drift_mev_atom_ps <= 0:
            raise ValueError("the NVE energy-drift limit must be positive")
        if self.thermostat_tau_fs <= 0 or self.barostat_tau_fs <= 0:
            raise ValueError("thermostat and barostat damping times must be positive")
        if self.relax_fmax_ev_a <= 0 or self.relax_steps <= 0:
            raise ValueError("relaxation tolerance and step limit must be positive")
        if self.expected_model_state_dict_sha256 is not None:
            expected = self.expected_model_state_dict_sha256
            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                raise ValueError("expected model hash must be a lowercase SHA-256 digest")
        if len(self.supercell) != 3 or any(value <= 0 for value in self.supercell):
            raise ValueError("supercell must contain three positive integers")
        if self.thermostat.lower() not in {"nose-hoover", "berendsen", "berendsen_inhomogeneous"}:
            raise ValueError(f"unsupported thermostat {self.thermostat!r}")
        if self.equilibration_ensemble.lower() not in {"nvt", "npt"}:
            raise ValueError("equilibration must be NVT or NPT")
        if (
            self.equilibration_ensemble.lower() == "npt"
            and self.thermostat.lower() != "nose-hoover"
        ):
            raise ValueError("MTK NPT equilibration requires the Nose-Hoover chain")
        if self.production_ensemble.lower() not in {"nvt", "nve"}:
            raise ValueError("production must be fixed-cell NVT or NVE")
        if self.dopant_count < 0:
            raise ValueError("dopant_count cannot be negative")
        if bool(self.dopant) != bool(self.dopant_count):
            raise ValueError("dopant and dopant_count must be supplied together")
        if self.dopant and not self.allow_random_doping:
            raise ValueError(
                "random substitution on an ordered host is screening-only; "
                "set allow_random_doping=True explicitly or supply a measured doped CIF"
            )
        if not 0 <= self.fit_from_fraction < self.fit_to_fraction <= 1:
            raise ValueError("invalid MSD fit fractions")
        if not 0 < self.min_diffusive_exponent < self.max_diffusive_exponent:
            raise ValueError("invalid diffusive-exponent interval")


@dataclass
class DiffusionPoint:
    temperature: int
    diffusivity_cm2_s: float
    msd_slope_a2_ps: float
    fit_r2: float
    n_frames: int
    production_ps: float
    n_mobile: int
    wall_seconds: float
    trajectory: str | None = None
    diffusivity_stderr_cm2_s: float | None = None
    collective_diffusivity_cm2_s: float | None = None
    collective_diffusivity_stderr_cm2_s: float | None = None
    collective_to_tracer_ratio: float | None = None
    diffusive_exponent: float | None = None
    fit_start_ps: float | None = None
    fit_end_ps: float | None = None
    resolved: bool = True
    rejection_reasons: list[str] = field(default_factory=list)
    collective_resolved: bool = False
    collective_rejection_reasons: list[str] = field(default_factory=list)
    final_tracer_msd_a2: float | None = None
    final_collective_msd_a2: float | None = None
    temperature_mean_k: float | None = None
    temperature_std_k: float | None = None
    minimum_distance_angstrom: float | None = None
    protocol_fingerprint: str | None = None
    diagnostics_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArrheniusFit:
    activation_energy_ev: float
    activation_energy_stderr_ev: float
    prefactor_cm2_s: float
    r2: float
    n_points: int
    temperature_range_k: tuple[int, int]
    method: str = "ordinary_least_squares_log_d"
    reduced_chi_square: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float, float]:
    """Ordinary least squares retained for transparent fallback and unit tests."""
    n = len(xs)
    if n < 2:
        raise ValueError("need at least two points to fit")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("all x values identical; slope undefined")
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys)]
    ss_res = sum(value * value for value in residuals)
    ss_tot = sum((value - mean_y) ** 2 for value in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    stderr = math.sqrt(ss_res / (n - 2) / sxx) if n > 2 else float("nan")
    return slope, intercept, r2, stderr


def mean_squared_displacement(
    positions: Any,
    *,
    framework_positions: Any | None = None,
    framework_weights: Any | None = None,
    remove_drift: bool = True,
) -> Any:
    """Single-origin MSD compatibility helper with physically valid drift.

    Production analysis uses :func:`matfactory.transport.time_origin_averaged_msd`.
    If drift correction is requested here, a separate host-framework trajectory
    is mandatory; subtracting the mobile Li mean would erase concerted transport.
    """
    import numpy as np

    mobile = np.asarray(positions, dtype=float)
    if mobile.ndim != 3 or mobile.shape[-1] != 3:
        raise ValueError("positions must be (n_frames, n_atoms, 3)")
    displacement = mobile - mobile[0]
    if remove_drift:
        if framework_positions is None:
            raise ValueError("framework_positions are required for drift correction")
        framework = np.asarray(framework_positions, dtype=float)
        if framework.ndim != 3 or framework.shape[-1] != 3:
            raise ValueError("framework_positions must be (n_frames, n_atoms, 3)")
        if framework.shape[0] != mobile.shape[0] or framework.shape[1] == 0:
            raise ValueError("framework and mobile trajectories are incompatible")
        weights = None if framework_weights is None else np.asarray(framework_weights, dtype=float)
        drift = np.average(framework - framework[0], axis=1, weights=weights)
        displacement = displacement - drift[:, None, :]
    return (displacement * displacement).sum(axis=2).mean(axis=1)


def diffusivity_from_msd(
    msd_a2: Any,
    times_ps: Any,
    *,
    fit_from: float = 0.3,
    fit_to: float = 0.9,
) -> tuple[float, float, float]:
    """Legacy direct Einstein fit; production uses the diagnostic estimator."""
    import numpy as np

    msd = np.asarray(msd_a2, dtype=float)
    times = np.asarray(times_ps, dtype=float)
    if msd.size != times.size:
        raise ValueError("msd and time arrays must be the same length")
    start = int(fit_from * msd.size)
    stop = min(max(int(fit_to * msd.size), start + 2), msd.size)
    if stop - start < 2:
        raise ValueError("fit window too narrow; run more steps")
    slope, _intercept, r2, _stderr = linear_fit(
        list(times[start:stop]), list(msd[start:stop])
    )
    return slope / 6.0 * 1e-4, slope, r2


def fit_arrhenius(points: list[DiffusionPoint]) -> ArrheniusFit:
    """Fit D(T) without silently discarding unresolved or negative points."""
    if len(points) < 3:
        raise ValueError(f"need at least three temperatures, got {len(points)}")
    unresolved = [point.temperature for point in points if not point.resolved]
    if unresolved:
        raise ValueError(
            "diffusion is unresolved at temperatures "
            + ", ".join(str(value) for value in unresolved)
            + "; extend those trajectories before fitting"
        )
    nonpositive = [point.temperature for point in points if point.diffusivity_cm2_s <= 0]
    if nonpositive:
        raise ValueError(
            "non-positive diffusivity at temperatures "
            + ", ".join(str(value) for value in nonpositive)
        )

    temperatures = [point.temperature for point in points]
    uncertainties = [point.diffusivity_stderr_cm2_s for point in points]
    if all(value is not None and value > 0 for value in uncertainties):
        import numpy as np
        from scipy.optimize import curve_fit

        temp = np.asarray(temperatures, dtype=float)
        diffusion = np.asarray([point.diffusivity_cm2_s for point in points])
        sigma = np.asarray(uncertainties, dtype=float)

        def model(temperature: Any, prefactor: float, energy: float) -> Any:
            return prefactor * np.exp(-energy / (K_B_EV * temperature))

        initial_log_slope, initial_log_intercept, _r2, _stderr = linear_fit(
            [1.0 / value for value in temperatures],
            [math.log(value) for value in diffusion],
        )
        parameters, covariance = curve_fit(
            model,
            temp,
            diffusion,
            p0=(math.exp(initial_log_intercept), max(1e-6, -initial_log_slope * K_B_EV)),
            sigma=sigma,
            absolute_sigma=True,
            bounds=(0.0, math.inf),
            maxfev=20_000,
        )
        prediction = model(temp, *parameters)
        residual = diffusion - prediction
        total = float(np.sum((diffusion - diffusion.mean()) ** 2))
        r2 = 1.0 - float(np.sum(residual * residual)) / total if total > 0 else 0.0
        reduced_chi_square = (
            float(np.sum((residual / sigma) ** 2) / (len(points) - 2))
            if len(points) > 2
            else None
        )
        return ArrheniusFit(
            activation_energy_ev=float(parameters[1]),
            activation_energy_stderr_ev=float(math.sqrt(max(0.0, covariance[1, 1]))),
            prefactor_cm2_s=float(parameters[0]),
            r2=r2,
            n_points=len(points),
            temperature_range_k=(min(temperatures), max(temperatures)),
            method="nonlinear_weighted_least_squares_d",
            reduced_chi_square=reduced_chi_square,
        )

    inverse_temperature = [1.0 / value for value in temperatures]
    log_diffusion = [math.log(point.diffusivity_cm2_s) for point in points]
    slope, intercept, r2, stderr = linear_fit(inverse_temperature, log_diffusion)
    return ArrheniusFit(
        activation_energy_ev=-slope * K_B_EV,
        activation_energy_stderr_ev=abs(stderr) * K_B_EV,
        prefactor_cm2_s=math.exp(intercept),
        r2=r2,
        n_points=len(points),
        temperature_range_k=(min(temperatures), max(temperatures)),
        method="ordinary_least_squares_log_d_no_point_uncertainties",
    )


def unwrap_trajectory(frames: list[Any], indices: list[int] | None = None) -> Any:
    """Unwrap a fixed-cell periodic trajectory in fractional coordinates."""
    import numpy as np

    if not frames:
        raise ValueError("trajectory has no frames")
    cells = np.asarray([frame.get_cell() for frame in frames], dtype=float)
    if not np.allclose(cells, cells[0], rtol=1e-7, atol=1e-8):
        raise ValueError("production trajectory cell changes; use fixed-cell production")
    selection: Any = slice(None) if indices is None else indices
    fractional = np.asarray(
        [frame.get_scaled_positions(wrap=True)[selection] for frame in frames], dtype=float
    )
    deltas = np.diff(fractional, axis=0)
    deltas -= np.round(deltas)
    unwrapped = np.concatenate(
        [fractional[:1], fractional[:1] + np.cumsum(deltas, axis=0)], axis=0
    )
    return unwrapped @ cells[0]


def _resolve_project_path(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path.resolve()
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / path
    if candidate.exists():
        return candidate.resolve()
    raise FileNotFoundError(value)


def _load_structure(config: MDConfig) -> tuple[Any, dict[str, Any]]:
    from pymatgen.core import Structure

    from .structures import (
        fetch_structure,
        load_cif_preserving_disorder,
        order_llzto_cif,
        structure_fingerprint,
    )

    metadata: dict[str, Any]
    if config.structure_file:
        path = _resolve_project_path(config.structure_file)
        if path.name.endswith(".structure.json"):
            structure = Structure.from_dict(json.loads(path.read_text(encoding="utf-8")))
            parser_warnings: list[str] = []
            provenance_path = Path(
                str(path)[: -len(".structure.json")] + ".provenance.json"
            )
            derived_provenance = None
            if provenance_path.exists():
                derived_provenance = json.loads(
                    provenance_path.read_text(encoding="utf-8")
                )
                expected = (
                    derived_provenance.get("outputs", {})
                    .get("structure_json_sha256")
                )
                if expected != sha256_file(path):
                    raise RuntimeError(
                        "derived-structure provenance does not match structure JSON"
                    )
                expected_structure = derived_provenance.get("child", {}).get(
                    "structure_sha256"
                )
                if expected_structure != structure_fingerprint(structure):
                    raise RuntimeError(
                        "derived-structure provenance does not match loaded structure"
                    )
        elif path.suffix.lower() == ".cif":
            structure, parser_warnings = load_cif_preserving_disorder(path)
            derived_provenance = None
        else:
            structure = Structure.from_file(path)
            parser_warnings = []
            derived_provenance = None
        metadata = {
            "source_path": str(path),
            "source_sha256": sha256_file(path),
            "source_id": config.structure_id,
            "source_parser_warnings": parser_warnings,
        }
        if derived_provenance is not None:
            metadata["derived_structure_provenance"] = {
                "path": str(provenance_path),
                "sha256": sha256_file(provenance_path),
                "artifact_kind": derived_provenance.get("artifact_kind"),
                "parent_structure_sha256": derived_provenance.get("parent", {}).get(
                    "structure_sha256"
                ),
                "supercell_matrix": derived_provenance.get("supercell_matrix"),
                "size_multiplier": derived_provenance.get("size_multiplier"),
            }
        if not structure.is_ordered:
            structure, ordering = order_llzto_cif(
                path,
                seed=config.occupancy_seed,
                primitive=config.primitive_cell,
                min_li_li_distance_angstrom=config.min_initial_li_li_distance_angstrom,
            )
            metadata["ordering"] = ordering.as_dict()
    else:
        if not config.structure_id:
            raise ValueError("an exact structure_file or structure_id is required")
        structure, identifier = fetch_structure(
            config.formula,
            provider=config.structure_provider,
            index=config.structure_index,
            structure_id=config.structure_id,
        )
        metadata = {
            "source_id": identifier,
            "source_provider": config.structure_provider,
        }
    if not structure.is_ordered:
        raise ValueError("MD input remains disordered after structure preparation")
    if tuple(config.supercell) != (1, 1, 1):
        structure.make_supercell(list(config.supercell))
        metadata["supercell"] = list(config.supercell)
    if config.dopant:
        from .doping import make_doped_cell

        structure, doping = make_doped_cell(
            structure, config.dopant, config.dopant_count, seed=config.occupancy_seed
        )
        metadata["random_doping_screening_only"] = doping.as_dict()
    metadata["prepared_structure_sha256"] = structure_fingerprint(structure)
    metadata["prepared_summary"] = _structure_summary(structure)
    return structure, metadata


def _structure_summary(structure: Any) -> dict[str, Any]:
    import numpy as np

    from .structures import structure_fingerprint

    matrix = np.asarray(structure.distance_matrix, dtype=float)
    np.fill_diagonal(matrix, np.inf)
    summary: dict[str, Any] = {
        "formula": structure.composition.formula,
        "reduced_formula": structure.composition.reduced_formula,
        "n_sites": len(structure),
        "ordered": bool(structure.is_ordered),
        "lattice_matrix_angstrom": structure.lattice.matrix.tolist(),
        "volume_angstrom3": float(structure.volume),
        "density_g_cm3": float(structure.density),
        "minimum_distance_angstrom": float(matrix.min()),
        "structure_sha256": structure_fingerprint(structure),
    }
    try:
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

        analyzer = SpacegroupAnalyzer(structure, symprec=0.1)
        summary["ordered_space_group_symbol"] = analyzer.get_space_group_symbol()
        summary["ordered_space_group_number"] = analyzer.get_space_group_number()
    except Exception as exc:
        summary["symmetry_error"] = f"{type(exc).__name__}: {exc}"
    return summary


def _write_structure(structure: Any, prefix: Path) -> dict[str, str]:
    from pymatgen.io.cif import CifWriter

    cif_path = Path(f"{prefix}.cif")
    json_path = Path(f"{prefix}.structure.json")
    atomic_write_text(cif_path, str(CifWriter(structure, symprec=None)))
    atomic_write_json(json_path, structure.as_dict())
    return {"cif": str(cif_path), "pymatgen_json": str(json_path)}


def _relax(
    structure: Any,
    model: Any,
    config: MDConfig,
    run_path: Path,
    *,
    model_metadata: dict[str, Any],
    quiet: bool,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    from pymatgen.core import Structure

    from .structures import structure_fingerprint

    relaxed_path = run_path / "relaxed.structure.json"
    report_path = run_path / "relaxation.json"
    input_hash = structure_fingerprint(structure)
    relaxation_protocol = {
        "input_structure_sha256": input_hash,
        "model_state_dict_sha256": model_metadata["state_dict_sha256"],
        "performed": config.relax_structure,
        "relax_cell": config.relax_cell,
        "fmax_target_ev_a": config.relax_fmax_ev_a,
        "max_steps": config.relax_steps,
    }
    relaxation_fingerprint = fingerprint(relaxation_protocol)
    if relaxed_path.exists() and report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("input_structure_sha256") != input_hash:
            raise RuntimeError("stored relaxation belongs to a different input structure")
        if report.get("relaxation_fingerprint") != relaxation_fingerprint:
            raise RuntimeError(
                "stored relaxation belongs to a different model or relaxation protocol"
            )
        relaxed = Structure.from_dict(json.loads(relaxed_path.read_text(encoding="utf-8")))
        if structure_fingerprint(relaxed) != report.get("output_structure_sha256"):
            raise RuntimeError("stored relaxed structure hash does not match relaxation report")
        return relaxed, report

    _write_structure(structure, run_path / "input")
    if not config.relax_structure:
        report = {
            "performed": False,
            "relaxation_fingerprint": relaxation_fingerprint,
            "relaxation_protocol": relaxation_protocol,
            "input_structure_sha256": input_hash,
            "output_structure_sha256": input_hash,
            "warning": "structure relaxation disabled explicitly",
        }
        atomic_write_json(relaxed_path, structure.as_dict())
        atomic_write_json(report_path, report)
        return structure, report

    from chgnet.model.dynamics import StructOptimizer

    optimizer = StructOptimizer(model=model, use_device=config.device)
    stream: Any = contextlib.nullcontext()
    if quiet:
        stream = contextlib.redirect_stdout(io.StringIO())
    with stream:
        result = optimizer.relax(
            structure,
            fmax=config.relax_fmax_ev_a,
            steps=config.relax_steps,
            relax_cell=config.relax_cell,
            verbose=not quiet,
        )
    relaxed = result["final_structure"]
    observer = result["trajectory"]
    max_forces = [float(np.linalg.norm(forces, axis=1).max()) for forces in observer.forces]
    report = {
        "performed": True,
        "relaxation_fingerprint": relaxation_fingerprint,
        "relaxation_protocol": relaxation_protocol,
        "input_structure_sha256": input_hash,
        "output_structure_sha256": structure_fingerprint(relaxed),
        "fmax_target_ev_a": config.relax_fmax_ev_a,
        "max_steps": config.relax_steps,
        "relax_cell": config.relax_cell,
        "n_observations": len(observer),
        "converged": bool(max_forces and max_forces[-1] <= config.relax_fmax_ev_a * 1.05),
        "energy_ev": [float(value) for value in observer.energies],
        "max_force_ev_a": max_forces,
        "volume_angstrom3": [float(abs(np.linalg.det(cell))) for cell in observer.cells],
        "initial_summary": _structure_summary(structure),
        "final_summary": _structure_summary(relaxed),
    }
    atomic_write_json(relaxed_path, relaxed.as_dict())
    atomic_write_json(report_path, report)
    _write_structure(relaxed, run_path / "relaxed")
    if not report["converged"]:
        raise RuntimeError(
            f"structure relaxation did not reach {config.relax_fmax_ev_a} eV/A; "
            f"final maximum force was {max_forces[-1] if max_forces else 'unknown'}"
        )
    return relaxed, report


def _source_files(project_root: Path, structure_metadata: dict[str, Any]) -> dict[str, str]:
    # Fingerprint only the transitive implementation of the MD calculation.
    # Literature/plotting code may evolve while a long run is resumable; the
    # fully materialized MDConfig already captures campaign-runner behavior.
    package = project_root / "src/matfactory"
    paths = [
        package / name
        for name in (
            "__init__.py",
            "doping.py",
            "mlipmd.py",
            "provenance.py",
            "structures.py",
            "transport.py",
        )
    ]
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        paths.append(pyproject)
    source_path = structure_metadata.get("source_path")
    if source_path:
        paths.append(Path(source_path))
    return file_manifest(paths, root=project_root)


def _model_metadata(model: Any, model_name: str) -> dict[str, Any]:
    """Hash every model parameter so a named default cannot change silently."""
    digest = hashlib.sha256()
    parameters = model.state_dict()
    total_parameters = 0
    for name in sorted(parameters):
        tensor = parameters[name].detach().cpu().contiguous()
        shape = tuple(int(value) for value in tensor.shape)
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(json.dumps(shape, separators=(",", ":")).encode("ascii"))
        digest.update(tensor.numpy().tobytes(order="C"))
        total_parameters += int(tensor.numel())
    return {
        "configured_name": model_name,
        "python_class": f"{type(model).__module__}.{type(model).__qualname__}",
        "n_parameter_tensors": len(parameters),
        "n_parameters": total_parameters,
        "state_dict_sha256": digest.hexdigest(),
    }


def _prepare_manifest(
    config: MDConfig,
    structure_metadata: dict[str, Any],
    run_path: Path,
    model_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    project_root = Path(__file__).resolve().parents[2]
    versions = environment_versions(
        ("matfactory", "chgnet", "ase", "pymatgen", "numpy", "scipy", "torch")
    )
    source_files = _source_files(project_root, structure_metadata)
    protocol_payload = {
        "config": config.as_dict(),
        "prepared_structure_sha256": structure_metadata["prepared_structure_sha256"],
        "model": model_metadata,
        "source_files": source_files,
        "environment": versions,
    }
    protocol_fingerprint = fingerprint(protocol_payload)
    manifest_path = run_path / "run_manifest.json"
    manifest = {
        "schema_version": "1.0",
        "protocol_fingerprint": protocol_fingerprint,
        **protocol_payload,
        "structure": structure_metadata,
        "git": git_state(project_root),
        "created_unix_time": time.time(),
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("protocol_fingerprint") != protocol_fingerprint:
            raise RuntimeError(
                "run directory protocol mismatch; use a new directory instead of "
                "mixing results from changed code, config, structure, or packages"
            )
        return existing, protocol_fingerprint
    atomic_write_json(manifest_path, manifest)
    return manifest, protocol_fingerprint


def _trajectory_diagnostics(
    frames: list[Any], target_temperature: float, *, frame_ps: float
) -> dict[str, Any]:
    import numpy as np

    temperatures: list[float] = []
    energies: list[float] = []
    total_energies: list[float] = []
    volumes: list[float] = []
    minima: list[float] = []
    stride = max(1, len(frames) // 50)
    for index, frame in enumerate(frames):
        try:
            temperatures.append(float(frame.get_temperature()))
        except Exception:
            pass
        try:
            energies.append(float(frame.get_potential_energy()) / len(frame))
        except Exception:
            pass
        try:
            total_energies.append(float(frame.get_total_energy()) / len(frame))
        except Exception:
            pass
        volumes.append(float(frame.get_volume()))
        if index % stride == 0 or index == len(frames) - 1:
            distances = frame.get_all_distances(mic=True)
            distances[distances == 0] = np.inf
            minima.append(float(distances.min()))
    report: dict[str, Any] = {
        "target_temperature_k": target_temperature,
        "n_frames": len(frames),
        "volume_mean_angstrom3": float(np.mean(volumes)),
        "volume_std_angstrom3": float(np.std(volumes)),
        "minimum_distance_angstrom": min(minima),
    }
    if temperatures:
        report.update(
            temperature_mean_k=float(np.mean(temperatures)),
            temperature_std_k=float(np.std(temperatures, ddof=1)) if len(temperatures) > 1 else 0.0,
            temperature_min_k=min(temperatures),
            temperature_max_k=max(temperatures),
        )
    if energies:
        report.update(
            potential_energy_mean_ev_atom=float(np.mean(energies)),
            potential_energy_std_ev_atom=float(np.std(energies, ddof=1)) if len(energies) > 1 else 0.0,
            potential_energy_first_ev_atom=energies[0],
            potential_energy_last_ev_atom=energies[-1],
        )
    if len(total_energies) >= 2:
        times = np.arange(len(total_energies), dtype=float) * frame_ps
        slope, intercept = np.polyfit(times, np.asarray(total_energies), 1)
        report.update(
            total_energy_first_ev_atom=total_energies[0],
            total_energy_last_ev_atom=total_energies[-1],
            total_energy_linear_intercept_ev_atom=float(intercept),
            total_energy_drift_ev_atom_ps=float(slope),
            total_energy_drift_mev_atom_ps=float(slope * 1_000.0),
        )
    return report


def _make_ase_dynamics(
    atoms: Any,
    *,
    ensemble: str,
    thermostat: str,
    temperature: float,
    timestep_fs: float,
    thermostat_tau_fs: float,
    pressure_gpa: float,
    barostat_tau_fs: float,
) -> Any:
    """Use current ASE integrators instead of CHGNet's deprecated MD wrapper."""
    from ase import units
    from ase.md.nose_hoover_chain import IsotropicMTKNPT, NoseHooverChainNVT
    from ase.md.nvtberendsen import NVTBerendsen
    from ase.md.verlet import VelocityVerlet

    name = ensemble.lower()
    coupling = thermostat.lower()
    timestep = timestep_fs * units.fs
    if name == "nve":
        return VelocityVerlet(atoms, timestep=timestep)
    if name == "nvt":
        if coupling == "nose-hoover":
            return NoseHooverChainNVT(
                atoms,
                timestep=timestep,
                temperature_K=temperature,
                tdamp=thermostat_tau_fs * units.fs,
                tchain=3,
            )
        if coupling.startswith("berendsen"):
            return NVTBerendsen(
                atoms,
                timestep=timestep,
                temperature_K=temperature,
                taut=thermostat_tau_fs * units.fs,
                fixcm=True,
            )
    if name == "npt" and coupling == "nose-hoover":
        return IsotropicMTKNPT(
            atoms,
            timestep=timestep,
            temperature_K=temperature,
            pressure_au=pressure_gpa * units.GPa,
            tdamp=thermostat_tau_fs * units.fs,
            pdamp=barostat_tau_fs * units.fs,
            tchain=3,
            pchain=3,
        )
    raise ValueError(f"unsupported ASE dynamics combination: {ensemble}/{thermostat}")


def run_temperature_point(
    structure: Any,
    model: Any,
    temperature: int,
    config: MDConfig,
    *,
    run_dir: Path,
    protocol_fingerprint: str,
    quiet: bool = True,
) -> DiffusionPoint:
    """Equilibrate, produce a clean fixed-cell trajectory, and assess transport."""
    import numpy as np
    from ase.md import MDLogger
    from ase.md.velocitydistribution import (
        MaxwellBoltzmannDistribution,
        Stationary,
    )
    from ase.io.trajectory import Trajectory
    from chgnet.model.dynamics import CHGNetCalculator
    from pymatgen.io.ase import AseAtomsAdaptor

    run_dir.mkdir(parents=True, exist_ok=True)
    tag = f"T{temperature}"
    trajectory_path = run_dir / f"{tag}.traj"
    diagnostics_path = run_dir / f"{tag}.transport.json"
    seed = config.seed + temperature * 1_009
    started = time.time()
    atoms = AseAtomsAdaptor.get_atoms(structure.copy())
    atoms.calc = CHGNetCalculator(model=model, use_device=config.device)
    MaxwellBoltzmannDistribution(
        atoms,
        temperature_K=temperature,
        force_temp=True,
        rng=np.random.default_rng(seed),
    )
    Stationary(atoms, preserve_temperature=True)

    equilibration = _make_ase_dynamics(
        atoms,
        ensemble=config.equilibration_ensemble,
        thermostat=config.thermostat,
        temperature=temperature,
        timestep_fs=config.timestep_fs,
        thermostat_tau_fs=config.thermostat_tau_fs,
        pressure_gpa=config.pressure_gpa,
        barostat_tau_fs=config.barostat_tau_fs,
    )
    equilibration_logger = MDLogger(
        equilibration,
        atoms,
        str(run_dir / f"{tag}.equilibration.log"),
        mode="w",
    )
    equilibration.attach(equilibration_logger, interval=config.loginterval)
    equilibration.run(config.equilibration_steps)
    equilibration_logger.close()

    production = _make_ase_dynamics(
        atoms,
        ensemble=config.production_ensemble,
        thermostat=config.thermostat,
        temperature=temperature,
        timestep_fs=config.timestep_fs,
        thermostat_tau_fs=config.thermostat_tau_fs,
        pressure_gpa=config.pressure_gpa,
        barostat_tau_fs=config.barostat_tau_fs,
    )
    production_logger = MDLogger(
        production,
        atoms,
        str(run_dir / f"{tag}.production.log"),
        mode="w",
    )
    trajectory = Trajectory(str(trajectory_path), "w", atoms)
    trajectory.write()
    production.attach(trajectory.write, interval=config.loginterval)
    production.attach(production_logger, interval=config.loginterval)
    production.run(config.production_steps)
    production_logger.close()
    trajectory.close()
    wall_seconds = time.time() - started

    frames = list(Trajectory(str(trajectory_path)))
    if len(frames) < 12:
        raise RuntimeError(f"only {len(frames)} production frames at {temperature} K")
    symbols = frames[0].get_chemical_symbols()
    mobile = [index for index, symbol in enumerate(symbols) if symbol == config.mobile_species]
    framework = [index for index, symbol in enumerate(symbols) if symbol != config.mobile_species]
    if not mobile or not framework:
        raise RuntimeError("mobile and host-framework atom selections must both be non-empty")
    unwrapped = unwrap_trajectory(frames)
    frame_ps = config.loginterval * config.timestep_fs / 1000.0
    masses = frames[0].get_masses()[framework]
    estimate = estimate_transport(
        unwrapped[:, mobile],
        unwrapped[:, framework],
        frame_ps=frame_ps,
        framework_weights=masses,
        n_blocks=config.uncertainty_blocks,
        max_lags=config.max_lags,
        fit_from_fraction=config.fit_from_fraction,
        fit_to_fraction=config.fit_to_fraction,
        min_final_msd_a2=config.min_final_msd_a2,
        alpha_range=(config.min_diffusive_exponent, config.max_diffusive_exponent),
        max_relative_stderr=config.max_relative_diffusivity_stderr,
    )
    diagnostics = _trajectory_diagnostics(frames, temperature, frame_ps=frame_ps)
    reasons = list(estimate.rejection_reasons)
    collective_reasons = list(estimate.collective_rejection_reasons)
    mean_temperature = diagnostics.get("temperature_mean_k")
    if mean_temperature is None:
        reasons.append("temperature_diagnostics_unavailable")
        collective_reasons.append("temperature_diagnostics_unavailable")
    elif abs(mean_temperature - temperature) / temperature > 0.10:
        reasons.append("production_temperature_outside_10_percent")
        collective_reasons.append("production_temperature_outside_10_percent")
    if diagnostics["minimum_distance_angstrom"] < 0.8:
        reasons.append("unphysical_close_contact")
        collective_reasons.append("unphysical_close_contact")
    if config.production_ensemble.lower() == "nve":
        drift = diagnostics.get("total_energy_drift_mev_atom_ps")
        if drift is None:
            reasons.append("nve_energy_drift_unavailable")
            collective_reasons.append("nve_energy_drift_unavailable")
        elif abs(drift) > config.max_abs_nve_energy_drift_mev_atom_ps:
            reasons.append("nve_energy_drift_too_large")
            collective_reasons.append("nve_energy_drift_too_large")
    resolved = not reasons
    collective_resolved = not collective_reasons
    payload = {
        "schema_version": "1.0",
        "protocol_fingerprint": protocol_fingerprint,
        "temperature_k": temperature,
        "velocity_seed": seed,
        "transport": estimate.as_dict(),
        "trajectory_diagnostics": diagnostics,
        "resolved_after_all_checks": resolved,
        "rejection_reasons_after_all_checks": reasons,
        "collective_resolved_after_all_checks": collective_resolved,
        "collective_rejection_reasons_after_all_checks": collective_reasons,
    }
    atomic_write_json(diagnostics_path, payload)
    final_structure = AseAtomsAdaptor.get_structure(frames[-1])
    _write_structure(final_structure, run_dir / f"{tag}.final")

    tracer = estimate.tracer
    collective = estimate.collective
    point = DiffusionPoint(
        temperature=temperature,
        diffusivity_cm2_s=tracer.diffusivity_cm2_s,
        diffusivity_stderr_cm2_s=tracer.diffusivity_stderr_cm2_s,
        collective_diffusivity_cm2_s=collective.diffusivity_cm2_s,
        collective_diffusivity_stderr_cm2_s=collective.diffusivity_stderr_cm2_s,
        collective_to_tracer_ratio=estimate.collective_to_tracer_ratio,
        msd_slope_a2_ps=tracer.slope_a2_ps,
        fit_r2=tracer.r2,
        diffusive_exponent=tracer.diffusive_exponent,
        fit_start_ps=tracer.fit_start_ps,
        fit_end_ps=tracer.fit_end_ps,
        resolved=resolved,
        rejection_reasons=reasons,
        collective_resolved=collective_resolved,
        collective_rejection_reasons=collective_reasons,
        final_tracer_msd_a2=estimate.final_tracer_msd_a2,
        final_collective_msd_a2=estimate.final_collective_msd_a2,
        n_frames=len(frames),
        production_ps=(len(frames) - 1) * frame_ps,
        n_mobile=len(mobile),
        wall_seconds=wall_seconds,
        trajectory=str(trajectory_path),
        temperature_mean_k=mean_temperature,
        temperature_std_k=diagnostics.get("temperature_std_k"),
        minimum_distance_angstrom=diagnostics.get("minimum_distance_angstrom"),
        protocol_fingerprint=protocol_fingerprint,
        diagnostics_path=str(diagnostics_path),
    )
    if not quiet:
        state = "resolved" if resolved else "UNRESOLVED: " + ",".join(reasons)
        print(
            f"{temperature} K D*={point.diffusivity_cm2_s:.3e} +/- "
            f"{(point.diffusivity_stderr_cm2_s or 0):.1e} cm2/s "
            f"alpha={point.diffusive_exponent} ({state}, {wall_seconds / 60:.1f} min)"
        )
    return point


def run_series(
    config: MDConfig,
    *,
    run_dir: Path | str = "runs/llzto",
    quiet: bool = False,
) -> dict[str, Any]:
    """Run or strictly resume one configuration replica across temperatures."""
    from chgnet.model import CHGNet

    config.validate()
    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    structure, structure_metadata = _load_structure(config)

    output_context: Any = contextlib.nullcontext()
    if quiet:
        output_context = contextlib.redirect_stdout(io.StringIO())
    with output_context:
        model = CHGNet.load()
    model_metadata = _model_metadata(model, config.model_name)
    if (
        config.expected_model_state_dict_sha256 is not None
        and model_metadata["state_dict_sha256"]
        != config.expected_model_state_dict_sha256
    ):
        raise RuntimeError(
            "loaded model weights do not match expected_model_state_dict_sha256: "
            f"expected {config.expected_model_state_dict_sha256}, got "
            f"{model_metadata['state_dict_sha256']}"
        )
    manifest, protocol_fingerprint = _prepare_manifest(
        config, structure_metadata, run_path, model_metadata
    )
    relaxed, relaxation = _relax(
        structure,
        model,
        config,
        run_path,
        model_metadata=model_metadata,
        quiet=quiet,
    )
    manifest["relaxation"] = relaxation
    atomic_write_json(run_path / "run_manifest.json", manifest)

    points_directory = run_path / "points"
    points_directory.mkdir(parents=True, exist_ok=True)
    done: dict[int, DiffusionPoint] = {}
    for temperature in config.temperatures:
        point_path = points_directory / f"T{temperature}.json"
        if point_path.exists():
            data = json.loads(point_path.read_text(encoding="utf-8"))
            if data.get("protocol_fingerprint") != protocol_fingerprint:
                raise RuntimeError(f"{point_path} belongs to a different protocol")
            done[temperature] = DiffusionPoint(**data["point"])
            if not quiet:
                print(f"resuming {temperature} K from {point_path}")
            continue
        point = run_temperature_point(
            relaxed,
            model,
            temperature,
            config,
            run_dir=run_path,
            protocol_fingerprint=protocol_fingerprint,
            quiet=quiet,
        )
        done[temperature] = point
        atomic_write_json(
            point_path,
            {
                "protocol_fingerprint": protocol_fingerprint,
                "point": point.as_dict(),
            },
        )

    points = [done[temperature] for temperature in sorted(done)]
    result: dict[str, Any] = {
        "schema_version": "2.1",
        "protocol_fingerprint": protocol_fingerprint,
        "config": config.as_dict(),
        "structure": structure_metadata,
        "relaxation": relaxation,
        "points": [point.as_dict() for point in points],
    }
    tracer_resolved = False
    collective_resolved = False
    try:
        result["arrhenius"] = fit_arrhenius(points).as_dict()
        tracer_resolved = True
    except ValueError as exc:
        result["arrhenius_error"] = str(exc)

    collective_points = [
        replace(
            point,
            diffusivity_cm2_s=(
                point.collective_diffusivity_cm2_s
                if point.collective_diffusivity_cm2_s is not None
                else 0.0
            ),
            diffusivity_stderr_cm2_s=point.collective_diffusivity_stderr_cm2_s,
            resolved=point.collective_resolved,
            rejection_reasons=point.collective_rejection_reasons,
        )
        for point in points
    ]
    try:
        result["arrhenius_collective"] = fit_arrhenius(collective_points).as_dict()
        collective_resolved = True
    except ValueError as exc:
        result["arrhenius_collective_error"] = str(exc)

    if tracer_resolved and collective_resolved:
        result["status"] = "complete_resolved"
    elif tracer_resolved:
        result["status"] = "complete_resolved_tracer_only"
    elif collective_resolved:
        result["status"] = "complete_resolved_collective_only"
    else:
        result["status"] = "complete_but_unresolved"
    atomic_write_json(run_path / "result.json", result)
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Auditable CHGNet transport workflow")
    parser.add_argument("--run-dir", default="runs/llzto")
    parser.add_argument("--structure-file", default="data/structures/raw/cod_1545083.cif")
    parser.add_argument("--structure-id", default="COD-1545083")
    parser.add_argument("--formula", default="Li6.5La3Zr1.5Ta0.5O12")
    parser.add_argument("--occupancy-seed", type=int, default=0)
    parser.add_argument("--velocity-seed", type=int, default=0)
    parser.add_argument(
        "--conventional-cell",
        action="store_true",
        help="use the 188-atom conventional cubic cell instead of the 94-atom primitive cell",
    )
    parser.add_argument("--temperatures", default="700,750,800,850,900")
    parser.add_argument("--production-steps", type=int, default=50_000)
    parser.add_argument("--equilibration-steps", type=int, default=5_000)
    parser.add_argument("--timestep-fs", type=float, default=2.0)
    parser.add_argument("--loginterval", type=int, default=50)
    parser.add_argument("--supercell", default="1,1,1")
    parser.add_argument("--thermostat", default="Nose-Hoover")
    parser.add_argument("--equilibration-ensemble", default="nvt")
    parser.add_argument("--production-ensemble", default="nvt")
    parser.add_argument("--skip-relax", action="store_true")
    parser.add_argument("--fixed-cell-relax", action="store_true")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    config = MDConfig(
        formula=args.formula,
        structure_file=args.structure_file or None,
        structure_id=args.structure_id or None,
        occupancy_seed=args.occupancy_seed,
        primitive_cell=not args.conventional_cell,
        seed=args.velocity_seed,
        temperatures=tuple(
            int(value) for value in args.temperatures.split(",") if value.strip()
        ),
        production_steps=args.production_steps,
        equilibration_steps=args.equilibration_steps,
        timestep_fs=args.timestep_fs,
        loginterval=args.loginterval,
        supercell=tuple(int(value) for value in args.supercell.split(",")),
        thermostat=args.thermostat,
        equilibration_ensemble=args.equilibration_ensemble,
        production_ensemble=args.production_ensemble,
        relax_structure=not args.skip_relax,
        relax_cell=not args.fixed_cell_relax,
        device=args.device,
    )
    result = run_series(config, run_dir=args.run_dir, quiet=args.quiet)
    if "arrhenius" in result:
        fit = result["arrhenius"]
        print(
            f"Ea = {fit['activation_energy_ev']:.3f} +/- "
            f"{fit['activation_energy_stderr_ev']:.3f} eV "
            f"({fit['method']}, r2={fit['r2']:.4f})"
        )
    else:
        print("No defensible Arrhenius fit:", result.get("arrhenius_error"))


if __name__ == "__main__":
    main()
