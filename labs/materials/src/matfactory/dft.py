"""Auditable snapshot selection and Quantum ESPRESSO validation helpers.

The DFT labels produced by this module are deliberately kept separate from the
MD campaign.  Snapshot identities and numerical settings are frozen before a
``pw.x`` output is parsed, so model errors cannot influence which structures
enter the validation set.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .provenance import (
    atomic_write_json,
    atomic_write_text,
    fingerprint,
    sha256_file,
)

RY_TO_EV = 13.605693122994
BOHR_TO_ANGSTROM = 0.529177210903
RY_BOHR_TO_EV_ANGSTROM = RY_TO_EV / BOHR_TO_ANGSTROM
KBAR_TO_GPA = 0.1
EV_ANGSTROM3_TO_GPA = 160.2176634
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
STRESS_CONVENTION = "positive-tension: (1/V) dE/dstrain"


@dataclass(frozen=True)
class QEResult:
    """Final observables from one completed ``pw.x`` calculation."""

    total_energy_ev: float
    forces_ev_angstrom: tuple[tuple[float, float, float], ...]
    stress_gpa: tuple[tuple[float, float, float], ...]
    qe_printed_stress_gpa: tuple[tuple[float, float, float], ...]
    pressure_gpa: float | None
    scf_iterations: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_energy_ev": self.total_energy_ev,
            "forces_ev_angstrom": [list(row) for row in self.forces_ev_angstrom],
            "stress_gpa": [list(row) for row in self.stress_gpa],
            "stress_convention": STRESS_CONVENTION,
            "qe_printed_stress_gpa": [
                list(row) for row in self.qe_printed_stress_gpa
            ],
            "qe_printed_stress_convention": "positive-compression",
            "pressure_gpa": self.pressure_gpa,
            "scf_iterations": self.scf_iterations,
        }


def _md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {source}")
    return payload


def load_pseudopotential_manifest(
    path: Path | str,
    *,
    pseudo_dir: Path | str | None = None,
    verify_files: bool = False,
) -> dict[str, Any]:
    """Load a pinned pseudopotential manifest and optionally verify every UPF."""
    source = Path(path)
    payload = _read_json(source)
    if payload.get("schema_version") != "1.0":
        raise ValueError("pseudopotential manifest schema_version must be '1.0'")
    elements = payload.get("elements")
    if not isinstance(elements, dict) or not elements:
        raise ValueError("pseudopotential manifest has no elements")
    for symbol, record in elements.items():
        if not isinstance(record, dict) or not record.get("filename"):
            raise ValueError(f"invalid pseudopotential record for {symbol}")
        for field in ("md5", "sha256", "cutoff_wfc_ry", "cutoff_rho_ry"):
            if not record.get(field):
                raise ValueError(f"pseudopotential {symbol} has no {field}")

    if verify_files:
        if pseudo_dir is None:
            raise ValueError("pseudo_dir is required when verify_files is true")
        root = Path(pseudo_dir)
        for symbol, record in elements.items():
            item = root / record["filename"]
            if not item.is_file():
                raise FileNotFoundError(
                    f"pseudopotential for {symbol} not found: {item}"
                )
            if _md5_file(item) != record["md5"]:
                raise RuntimeError(f"MD5 mismatch for pseudopotential {symbol}: {item}")
            if sha256_file(item) != record["sha256"]:
                raise RuntimeError(
                    f"SHA-256 mismatch for pseudopotential {symbol}: {item}"
                )
    payload["manifest_path"] = str(source.resolve())
    payload["manifest_sha256"] = sha256_file(source)
    return payload


def atoms_fingerprint(atoms: Any) -> str:
    """Hash only structure-defining quantities, excluding attached labels."""
    value = {
        "atomic_numbers": atoms.get_atomic_numbers().tolist(),
        "cell_angstrom": np.asarray(atoms.cell.array, dtype=float).tolist(),
        "positions_angstrom": np.asarray(atoms.positions, dtype=float).tolist(),
        "pbc": np.asarray(atoms.pbc, dtype=bool).tolist(),
    }
    return fingerprint(value)


def periodic_rmsd(first: Any, second: Any) -> float:
    """Order-preserving, translation-corrected periodic RMS displacement.

    MD keeps atom ordering fixed.  This metric intentionally does not solve an
    atom-assignment problem: swapping two chemically identical ions is a real
    change of the labelled trajectory and can encode a diffusion event.
    """
    first_numbers = np.asarray(first.get_atomic_numbers())
    second_numbers = np.asarray(second.get_atomic_numbers())
    if not np.array_equal(first_numbers, second_numbers):
        raise ValueError("RMSD structures have different atomic ordering")
    first_cell = np.asarray(first.cell.array, dtype=float)
    second_cell = np.asarray(second.cell.array, dtype=float)
    if (
        abs(np.linalg.det(first_cell)) < 1e-12
        or abs(np.linalg.det(second_cell)) < 1e-12
    ):
        raise ValueError("RMSD requires nonsingular periodic cells")

    first_frac = np.asarray(first.get_scaled_positions(wrap=True), dtype=float)
    second_frac = np.asarray(second.get_scaled_positions(wrap=True), dtype=float)
    delta_frac = second_frac - first_frac
    delta_frac -= np.rint(delta_frac)
    mean_cell = 0.5 * (first_cell + second_cell)
    delta = delta_frac @ mean_cell
    framework = first_numbers != 3
    reference = delta[framework] if np.any(framework) else delta
    delta -= np.mean(reference, axis=0)
    return float(np.sqrt(np.mean(np.sum(delta**2, axis=1))))


def _farthest_indices(
    frames: list[Any],
    candidates: list[int],
    count: int,
    *,
    min_frame_separation: int,
    min_rmsd_angstrom: float,
) -> list[int]:
    if count <= 0:
        return []
    if len(candidates) < count:
        raise ValueError(f"need {count} candidates, found {len(candidates)}")

    # A median anchor makes the procedure insensitive to whether a trajectory
    # happened to write an extra endpoint frame.
    selected = [candidates[len(candidates) // 2]]
    while len(selected) < count:
        allowed = [
            index
            for index in candidates
            if index not in selected
            and all(abs(index - chosen) >= min_frame_separation for chosen in selected)
        ]
        if not allowed:
            raise ValueError(
                "snapshot time-separation constraint leaves too few candidates"
            )
        scores = []
        for index in allowed:
            distance = min(
                periodic_rmsd(frames[index], frames[chosen]) for chosen in selected
            )
            scores.append((distance, -index, index))
        distance, _tie_break, chosen = max(scores)
        if distance < min_rmsd_angstrom:
            raise ValueError(
                f"only {len(selected)} snapshots exceed the preregistered "
                f"{min_rmsd_angstrom:g} A RMSD threshold"
            )
        selected.append(chosen)
    return sorted(selected)


def _clean_atoms(atoms: Any) -> Any:
    clean = atoms.copy()
    clean.calc = None
    if "momenta" in clean.arrays:
        del clean.arrays["momenta"]
    if "initial_magmoms" in clean.arrays:
        del clean.arrays["initial_magmoms"]
    clean.info.clear()
    return clean


def _write_extxyz(path: Path, atoms: Any) -> None:
    from ase.io import write

    stream = io.StringIO()
    write(stream, atoms, format="extxyz")
    atomic_write_text(path, stream.getvalue())


def _require_empty_destination(path: Path, *, purpose: str) -> None:
    """Create a destination only when no prior evidence would be overwritten."""
    if path.exists():
        if not path.is_dir():
            raise RuntimeError(f"{purpose} destination is not a directory: {path}")
        if any(path.iterdir()):
            raise RuntimeError(
                f"refusing to overwrite non-empty {purpose} destination: {path}"
            )
    else:
        path.mkdir(parents=True)


def select_snapshots(
    protocol_path: Path | str,
    *,
    out_dir: Path | str,
    project_root: Path | str = ".",
) -> dict[str, Any]:
    """Materialize a deterministic, label-blind validation snapshot set."""
    from ase.io import read

    protocol_source = Path(protocol_path).resolve()
    protocol = _read_json(protocol_source)
    if protocol.get("schema_version") != "1.0":
        raise ValueError("snapshot protocol schema_version must be '1.0'")
    selection_id = protocol.get("selection_id")
    if not isinstance(selection_id, str) or not SAFE_ID.fullmatch(selection_id):
        raise ValueError("selection_id must be a safe lowercase identifier")

    root = Path(project_root).resolve()
    destination = Path(out_dir).resolve()
    _require_empty_destination(destination, purpose="snapshot-selection")
    snapshots_dir = destination / "snapshots"
    snapshots_dir.mkdir()
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for spec in protocol.get("static_snapshots", []):
        snapshot_id = str(spec["snapshot_id"])
        if not SAFE_ID.fullmatch(snapshot_id) or snapshot_id in seen_ids:
            raise ValueError(f"unsafe or duplicate snapshot_id {snapshot_id!r}")
        source = (root / spec["structure"]).resolve()
        atoms = _clean_atoms(read(source, index=int(spec.get("frame_index", 0))))
        output = snapshots_dir / f"{snapshot_id}.extxyz"
        _write_extxyz(output, atoms)
        stored_atoms = read(output, index=0)
        seen_ids.add(snapshot_id)
        metadata = spec.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"snapshot metadata must be an object: {snapshot_id}")
        rows.append(
            {
                "snapshot_id": snapshot_id,
                "kind": "static",
                "temperature_k": spec.get("temperature_k"),
                "source_path": str(source),
                "source_sha256": sha256_file(source),
                "source_frame_index": int(spec.get("frame_index", 0)),
                "snapshot_path": str(output),
                "snapshot_sha256": sha256_file(output),
                "structure_fingerprint": atoms_fingerprint(stored_atoms),
                "n_atoms": len(atoms),
                "metadata": metadata,
            }
        )

    trajectory_specs = list(protocol.get("trajectory_strata", []))
    for matrix in protocol.get("trajectory_matrices", []):
        if not isinstance(matrix, dict):
            raise ValueError("trajectory_matrices entries must be objects")
        occupancies = matrix.get("occupancy_seeds")
        temperatures = matrix.get("temperatures_k")
        if not isinstance(occupancies, list) or not occupancies:
            raise ValueError("trajectory matrix has no occupancy seeds")
        if not isinstance(temperatures, list) or not temperatures:
            raise ValueError("trajectory matrix has no temperatures")
        shared = {
            key: value
            for key, value in matrix.items()
            if key
            not in {
                "occupancy_seeds",
                "temperatures_k",
                "trajectory_template",
                "id_prefix_template",
                "metadata",
            }
        }
        base_metadata = matrix.get("metadata", {})
        if not isinstance(base_metadata, dict):
            raise ValueError("trajectory-matrix metadata must be an object")
        for occupancy_seed in occupancies:
            for temperature_k in temperatures:
                format_values = {
                    "occupancy_seed": int(occupancy_seed),
                    "temperature_k": int(temperature_k),
                }
                trajectory_specs.append(
                    {
                        **shared,
                        "id_prefix": str(matrix["id_prefix_template"]).format(
                            **format_values
                        ),
                        "trajectory": str(matrix["trajectory_template"]).format(
                            **format_values
                        ),
                        "temperature_k": int(temperature_k),
                        "metadata": {
                            **base_metadata,
                            "occupancy_seed": int(occupancy_seed),
                        },
                    }
                )

    for spec in trajectory_specs:
        metadata = spec.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("trajectory-stratum metadata must be an object")
        source = (root / spec["trajectory"]).resolve()
        frames = list(read(source, index=":"))
        if not frames:
            raise ValueError(f"empty trajectory {source}")
        count = int(spec["count"])
        start = math.floor(float(spec.get("start_fraction", 0.0)) * (len(frames) - 1))
        stop = math.ceil(float(spec.get("stop_fraction", 1.0)) * (len(frames) - 1))
        if not 0 <= start <= stop < len(frames):
            raise ValueError(f"invalid frame fraction range for {source}")
        candidates = list(range(start, stop + 1))
        indices = _farthest_indices(
            frames,
            candidates,
            count,
            min_frame_separation=int(spec.get("min_frame_separation", 1)),
            min_rmsd_angstrom=float(spec.get("min_rmsd_angstrom", 0.0)),
        )
        source_hash = sha256_file(source)
        for ordinal, frame_index in enumerate(indices):
            snapshot_id = f"{spec['id_prefix']}-{ordinal:02d}"
            if not SAFE_ID.fullmatch(snapshot_id) or snapshot_id in seen_ids:
                raise ValueError(f"unsafe or duplicate snapshot_id {snapshot_id!r}")
            atoms = _clean_atoms(frames[frame_index])
            output = snapshots_dir / f"{snapshot_id}.extxyz"
            _write_extxyz(output, atoms)
            stored_atoms = read(output, index=0)
            seen_ids.add(snapshot_id)
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "kind": "trajectory",
                    "temperature_k": int(spec["temperature_k"]),
                    "source_path": str(source),
                    "source_sha256": source_hash,
                    "source_frame_index": frame_index,
                    "source_n_frames": len(frames),
                    "source_time_ps": round(
                        frame_index * float(spec["frame_spacing_ps"]), 12
                    ),
                    "snapshot_path": str(output),
                    "snapshot_sha256": sha256_file(output),
                    "structure_fingerprint": atoms_fingerprint(stored_atoms),
                    "n_atoms": len(atoms),
                    "metadata": metadata,
                }
            )

    expected = int(protocol["expected_snapshot_count"])
    if len(rows) != expected:
        raise ValueError(
            f"protocol expected {expected} snapshots, selected {len(rows)}"
        )
    manifest = {
        "schema_version": "1.0",
        "selection_id": selection_id,
        "selection_protocol_path": str(protocol_source),
        "selection_protocol_sha256": sha256_file(protocol_source),
        "selection_implementation_path": str(Path(__file__).resolve()),
        "selection_implementation_sha256": sha256_file(Path(__file__)),
        "selection_is_label_blind": True,
        "selection_algorithm": (
            "median-anchor farthest-point sampling using atom-order-preserving, "
            "framework-translation-corrected periodic RMSD; ties use the earliest frame"
        ),
        "n_snapshots": len(rows),
        "snapshots": rows,
    }
    manifest["snapshot_set_fingerprint"] = fingerprint(manifest)
    atomic_write_json(destination / "snapshot_manifest.json", manifest)
    return manifest


def _qe_value(value: Any) -> str:
    if isinstance(value, bool):
        return ".true." if value else ".false."
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.12g}"
    raise TypeError(f"unsupported Quantum ESPRESSO value {value!r}")


def _namelist(name: str, values: dict[str, Any]) -> list[str]:
    lines = [f"&{name.upper()}"]
    for key, value in values.items():
        lines.append(f"  {key} = {_qe_value(value)}")
    lines.append("/")
    return lines


def render_qe_input(
    atoms: Any,
    *,
    pseudopotentials: dict[str, dict[str, Any]],
    settings: dict[str, Any],
    prefix: str,
    pseudo_dir: str = "./pseudo",
    outdir: str = "./scratch",
) -> str:
    """Render a non-spin-polarized PBE single-point ``pw.x`` input."""
    from ase.data import atomic_masses, atomic_numbers

    if not SAFE_ID.fullmatch(prefix):
        raise ValueError(f"unsafe Quantum ESPRESSO prefix {prefix!r}")
    symbols = atoms.get_chemical_symbols()
    species = list(dict.fromkeys(symbols))
    missing = [symbol for symbol in species if symbol not in pseudopotentials]
    if missing:
        raise ValueError("no pseudopotential for: " + ", ".join(missing))
    kpoints = settings.get("kpoints", [1, 1, 1])
    if kpoints != "gamma":
        if not isinstance(kpoints, list) or len(kpoints) != 3:
            raise ValueError("kpoints must be 'gamma' or three integers")
        if any(int(value) < 1 for value in kpoints):
            raise ValueError("k-point dimensions must be positive")
    disk_io = str(settings.get("disk_io", "low"))
    if disk_io not in {"none", "low", "medium", "high"}:
        raise ValueError(f"unsupported Quantum ESPRESSO disk_io {disk_io!r}")

    lines = []
    lines.extend(
        _namelist(
            "control",
            {
                "calculation": "scf",
                "prefix": prefix,
                "pseudo_dir": pseudo_dir,
                "outdir": outdir,
                "tprnfor": True,
                "tstress": True,
                "disk_io": disk_io,
                "verbosity": "high",
            },
        )
    )
    lines.extend(
        _namelist(
            "system",
            {
                "ibrav": 0,
                "nat": len(atoms),
                "ntyp": len(species),
                "input_dft": "PBE",
                "ecutwfc": float(settings["ecutwfc_ry"]),
                "ecutrho": float(settings["ecutrho_ry"]),
                "occupations": "fixed",
                "nspin": 1,
                "nosym": True,
                "noinv": True,
            },
        )
    )
    lines.extend(
        _namelist(
            "electrons",
            {
                "conv_thr": float(settings["conv_thr_ry"]),
                "electron_maxstep": int(settings.get("electron_maxstep", 200)),
                "mixing_mode": str(settings.get("mixing_mode", "plain")),
                "mixing_beta": float(settings.get("mixing_beta", 0.3)),
                "diagonalization": str(settings.get("diagonalization", "david")),
            },
        )
    )
    lines.append("ATOMIC_SPECIES")
    for symbol in species:
        mass = atomic_masses[atomic_numbers[symbol]]
        lines.append(
            f"  {symbol:<2s} {mass:.8f} {pseudopotentials[symbol]['filename']}"
        )
    lines.append("ATOMIC_POSITIONS angstrom")
    for symbol, position in zip(symbols, np.asarray(atoms.positions)):
        lines.append(
            f"  {symbol:<2s} {position[0]: .12f} {position[1]: .12f} {position[2]: .12f}"
        )
    lines.append("CELL_PARAMETERS angstrom")
    for vector in np.asarray(atoms.cell.array):
        lines.append(f"  {vector[0]: .12f} {vector[1]: .12f} {vector[2]: .12f}")
    if kpoints == "gamma":
        lines.append("K_POINTS gamma")
    else:
        lines.append("K_POINTS automatic")
        lines.append("  " + " ".join(str(int(value)) for value in kpoints) + " 0 0 0")
    return "\n".join(lines) + "\n"


def prepare_qe_inputs(
    snapshot_manifest_path: Path | str,
    dft_protocol_path: Path | str,
    pseudopotential_manifest_path: Path | str,
    *,
    pseudo_dir: Path | str,
    out_dir: Path | str,
    qe_executable: Path | str | None = None,
) -> dict[str, Any]:
    """Freeze all inputs and manifests before any DFT label is observed."""
    from ase.io import read

    snapshots_source = Path(snapshot_manifest_path).resolve()
    protocol_source = Path(dft_protocol_path).resolve()
    pseudo_source = Path(pseudopotential_manifest_path).resolve()
    snapshots = _read_json(snapshots_source)
    protocol = _read_json(protocol_source)
    pseudos = load_pseudopotential_manifest(
        pseudo_source, pseudo_dir=pseudo_dir, verify_files=True
    )
    if protocol.get("schema_version") != "1.0":
        raise ValueError("DFT protocol schema_version must be '1.0'")
    protocol_id = protocol.get("protocol_id")
    if not isinstance(protocol_id, str) or not SAFE_ID.fullmatch(protocol_id):
        raise ValueError("DFT protocol_id must be a safe lowercase identifier")
    settings_list = protocol.get("calculations")
    if not isinstance(settings_list, list) or not settings_list:
        raise ValueError("DFT protocol contains no calculations")
    execution = protocol.get("execution_environment", {})
    expected_executable_hash = execution.get("pw_executable_sha256")
    project_root = Path(__file__).resolve().parents[2]
    environment_manifest_path = None
    if execution.get("manifest"):
        environment_manifest_path = Path(execution["manifest"])
        if not environment_manifest_path.is_absolute():
            environment_manifest_path = project_root / environment_manifest_path
        if sha256_file(environment_manifest_path) != execution.get("manifest_sha256"):
            raise RuntimeError(
                f"QE environment manifest hash mismatch: {environment_manifest_path}"
            )
    environment_lock_path = None
    if execution.get("explicit_lock"):
        environment_lock_path = Path(execution["explicit_lock"])
        if not environment_lock_path.is_absolute():
            environment_lock_path = project_root / environment_lock_path
        if sha256_file(environment_lock_path) != execution.get("explicit_lock_sha256"):
            raise RuntimeError(
                f"QE environment lock hash mismatch: {environment_lock_path}"
            )
    executable_path = Path(qe_executable).resolve() if qe_executable else None
    if expected_executable_hash:
        if executable_path is None:
            raise ValueError(
                "qe_executable is required by this DFT protocol for binary verification"
            )
        if sha256_file(executable_path) != expected_executable_hash:
            raise RuntimeError(
                f"Quantum ESPRESSO executable hash mismatch: {executable_path}"
            )

    destination = Path(out_dir).resolve()
    _require_empty_destination(destination, purpose="DFT-input")
    runs: list[dict[str, Any]] = []
    pseudo_root = Path(pseudo_dir).resolve()
    for snapshot in snapshots["snapshots"]:
        atoms = read(snapshot["snapshot_path"], index=0)
        if atoms_fingerprint(atoms) != snapshot["structure_fingerprint"]:
            raise RuntimeError(f"snapshot structure changed: {snapshot['snapshot_id']}")
        for settings in settings_list:
            label = str(settings["label"])
            if not SAFE_ID.fullmatch(label):
                raise ValueError(f"unsafe calculation label {label!r}")
            run_id = f"{snapshot['snapshot_id']}--{label}"
            run_dir = destination / run_id
            run_dir.mkdir()
            (run_dir / "scratch").mkdir()
            run_pseudos = run_dir / "pseudo"
            run_pseudos.mkdir()
            for record in pseudos["elements"].values():
                source = pseudo_root / record["filename"]
                target = run_pseudos / record["filename"]
                if not target.exists():
                    shutil.copy2(source, target)
                if sha256_file(target) != record["sha256"]:
                    raise RuntimeError(f"copied pseudopotential changed: {target}")
            text = render_qe_input(
                atoms,
                pseudopotentials=pseudos["elements"],
                settings=settings,
                prefix=run_id,
            )
            input_path = run_dir / "pw.in"
            atomic_write_text(input_path, text)
            run_manifest = {
                "schema_version": "1.0",
                "run_id": run_id,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_path": snapshot["snapshot_path"],
                "snapshot_sha256": snapshot["snapshot_sha256"],
                "structure_fingerprint": snapshot["structure_fingerprint"],
                "n_atoms": snapshot["n_atoms"],
                "settings": settings,
                "input_path": str(input_path),
                "input_sha256": sha256_file(input_path),
                "pseudopotential_manifest_sha256": pseudos["manifest_sha256"],
                "dft_implementation_sha256": sha256_file(Path(__file__)),
                "pw_executable_sha256": expected_executable_hash,
                "pseudopotentials": {
                    symbol: {
                        "filename": record["filename"],
                        "sha256": record["sha256"],
                    }
                    for symbol, record in pseudos["elements"].items()
                },
                "label_status": "not_run",
            }
            run_manifest["run_fingerprint"] = fingerprint(run_manifest)
            atomic_write_json(run_dir / "run_manifest.json", run_manifest)
            runs.append(run_manifest)

    campaign = {
        "schema_version": "1.0",
        "protocol_id": protocol_id,
        "snapshot_manifest_path": str(snapshots_source),
        "snapshot_manifest_sha256": sha256_file(snapshots_source),
        "dft_protocol_path": str(protocol_source),
        "dft_protocol_sha256": sha256_file(protocol_source),
        "pseudopotential_manifest_path": str(pseudo_source),
        "pseudopotential_manifest_sha256": sha256_file(pseudo_source),
        "dft_implementation_path": str(Path(__file__).resolve()),
        "dft_implementation_sha256": sha256_file(Path(__file__)),
        "pw_executable_path": str(executable_path) if executable_path else None,
        "pw_executable_sha256": expected_executable_hash,
        "qe_environment_manifest_path": (
            str(environment_manifest_path) if environment_manifest_path else None
        ),
        "qe_environment_manifest_sha256": execution.get("manifest_sha256"),
        "qe_environment_lock_path": (
            str(environment_lock_path) if environment_lock_path else None
        ),
        "qe_environment_lock_sha256": execution.get("explicit_lock_sha256"),
        "labels_seen_when_frozen": False,
        "n_runs": len(runs),
        "runs": runs,
    }
    campaign["campaign_fingerprint"] = fingerprint(campaign)
    atomic_write_json(destination / "dft_campaign_manifest.json", campaign)
    return campaign


_ENERGY = re.compile(r"!\s+total energy\s+=\s+([-+0-9.Ee]+)\s+Ry")
_FORCE = re.compile(
    r"atom\s+(\d+)\s+type\s+\d+\s+force\s+=\s+"
    r"([-+0-9.Ee]+)\s+([-+0-9.Ee]+)\s+([-+0-9.Ee]+)"
)
_FORCES_HEADER = re.compile(r"Forces acting on atoms\s+\(cartesian axes,\s*Ry/au\):")
_ITERATIONS = re.compile(r"convergence has been achieved in\s+(\d+) iterations")
_STRESS_HEADER = re.compile(
    r"total\s+stress\s+\(Ry/bohr\*\*3\)\s+\(kbar\)\s+P=\s*([-+0-9.Ee]+)"
)


def _parse_final_force_block(
    text: str, *, expected_n_atoms: int | None
) -> tuple[tuple[float, float, float], ...]:
    """Read total forces, excluding verbose QE force-decomposition blocks."""
    headers = list(_FORCES_HEADER.finditer(text))
    if not headers:
        raise ValueError("Quantum ESPRESSO output has no total-force header")

    rows: list[re.Match[str]] = []
    started = False
    for line in text[headers[-1].end() :].splitlines():
        match = _FORCE.search(line)
        if match:
            atom_index = int(match.group(1))
            if atom_index != len(rows) + 1:
                raise ValueError("Quantum ESPRESSO total-force rows are out of order")
            rows.append(match)
            started = True
            if expected_n_atoms is not None and len(rows) == expected_n_atoms:
                break
        elif started and line.strip():
            break

    if expected_n_atoms is not None and len(rows) != expected_n_atoms:
        raise ValueError(
            "Quantum ESPRESSO total-force block has "
            f"{len(rows)} rows; expected {expected_n_atoms}"
        )
    if not rows:
        raise ValueError("Quantum ESPRESSO output has no total forces")
    return tuple(
        tuple(float(match.group(axis)) * RY_BOHR_TO_EV_ANGSTROM for axis in (2, 3, 4))
        for match in rows
    )


def parse_pw_output(text: str, *, expected_n_atoms: int | None = None) -> QEResult:
    """Parse final observables and standardize stress to positive tension.

    Quantum ESPRESSO prints a pressure-sign tensor (positive compression) and
    reports ``P = trace(sigma_qe) / 3``. CHGNet and ASE use the energy-derivative
    convention ``stress = (1 / V) dE / dstrain`` (positive tension), so the
    standardized ``stress_gpa`` field is the negative of the tensor printed by
    QE. The unmodified printed tensor is retained for auditability.
    """
    if "JOB DONE." not in text:
        raise ValueError("Quantum ESPRESSO output is incomplete: JOB DONE not found")
    energies = [float(value) for value in _ENERGY.findall(text)]
    if not energies:
        raise ValueError("Quantum ESPRESSO output has no total energy")
    forces = _parse_final_force_block(
        text,
        expected_n_atoms=expected_n_atoms,
    )

    stress_matches = list(_STRESS_HEADER.finditer(text))
    if not stress_matches:
        raise ValueError("Quantum ESPRESSO output has no stress tensor")
    header = stress_matches[-1]
    tail = text[header.end() :].splitlines()
    qe_printed_rows: list[tuple[float, float, float]] = []
    for line in tail:
        values = line.split()
        if len(values) >= 6:
            try:
                qe_printed_rows.append(
                    tuple(float(value) * KBAR_TO_GPA for value in values[-3:])
                )
            except ValueError:
                continue
        if len(qe_printed_rows) == 3:
            break
    if len(qe_printed_rows) != 3:
        raise ValueError("Quantum ESPRESSO output has an incomplete stress tensor")
    standardized_rows = tuple(
        tuple(-component for component in row) for row in qe_printed_rows
    )
    iterations = [int(value) for value in _ITERATIONS.findall(text)]
    return QEResult(
        total_energy_ev=energies[-1] * RY_TO_EV,
        forces_ev_angstrom=forces,
        stress_gpa=standardized_rows,
        qe_printed_stress_gpa=tuple(qe_printed_rows),
        pressure_gpa=float(header.group(1)) * KBAR_TO_GPA,
        scf_iterations=iterations[-1] if iterations else None,
    )


def collect_qe_result(
    run_dir: Path | str,
    *,
    output_name: str = "pw.out",
    _allow_label_replacement: bool = False,
) -> dict[str, Any]:
    """Parse one frozen run without modifying its original input or output.

    Existing labels are immutable. A deliberate schema migration must use
    :func:`migrate_qe_stress_label`, which archives and hashes the old label
    before replacing it.
    """
    directory = Path(run_dir).resolve()
    manifest_path = directory / "run_manifest.json"
    manifest = _read_json(manifest_path)
    input_path = Path(manifest["input_path"])
    if sha256_file(input_path) != manifest["input_sha256"]:
        raise RuntimeError(f"DFT input changed after preregistration: {input_path}")
    output_path = directory / output_name
    result = parse_pw_output(
        output_path.read_text(encoding="utf-8", errors="replace"),
        expected_n_atoms=int(manifest["n_atoms"]),
    )
    label = {
        "schema_version": "1.1",
        "run_id": manifest["run_id"],
        "run_fingerprint": manifest["run_fingerprint"],
        "input_sha256": manifest["input_sha256"],
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "parser_implementation_path": str(Path(__file__).resolve()),
        "parser_implementation_sha256": sha256_file(Path(__file__)),
        "result": result.as_dict(),
    }
    label_path = directory / "dft_label.json"
    if label_path.exists() and not _allow_label_replacement:
        existing = _read_json(label_path)
        if existing == label:
            return existing
        raise RuntimeError(
            "refusing to overwrite an existing DFT label; use the explicit "
            f"stress-convention migration if applicable: {label_path}"
        )
    atomic_write_json(label_path, label)
    return label


def migrate_qe_stress_label(
    run_dir: Path | str, *, output_name: str = "pw.out"
) -> dict[str, Any]:
    """Migrate a legacy raw-QE stress label with a complete hash chain."""
    directory = Path(run_dir).resolve()
    label_path = directory / "dft_label.json"
    manifest_path = directory / "run_manifest.json"
    if not label_path.is_file():
        raise FileNotFoundError(label_path)
    legacy_text = label_path.read_text(encoding="utf-8")
    legacy = _read_json(label_path)
    legacy_result = legacy.get("result")
    if legacy.get("schema_version") != "1.0" or not isinstance(legacy_result, dict):
        raise ValueError(f"label is not a legacy schema-1.0 QE label: {label_path}")
    if "qe_printed_stress_gpa" in legacy_result or legacy_result.get(
        "stress_convention"
    ):
        raise ValueError(f"label already declares a stress convention: {label_path}")

    manifest = _read_json(manifest_path)
    input_path = Path(manifest["input_path"])
    output_path = directory / output_name
    checks = {
        "run_id": legacy.get("run_id") == manifest.get("run_id"),
        "run_fingerprint": legacy.get("run_fingerprint")
        == manifest.get("run_fingerprint"),
        "input_sha256": sha256_file(input_path)
        == manifest.get("input_sha256")
        == legacy.get("input_sha256"),
        "output_sha256": sha256_file(output_path) == legacy.get("output_sha256"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(
            f"legacy DFT-label provenance failed for {directory}: {', '.join(failed)}"
        )

    archive_path = directory / "dft_label.schema1.0-qe-printed-stress.json"
    if archive_path.exists():
        if archive_path.read_text(encoding="utf-8") != legacy_text:
            raise RuntimeError(f"legacy-label archive already differs: {archive_path}")
    else:
        atomic_write_text(archive_path, legacy_text)
    legacy_sha256 = sha256_file(archive_path)
    migrated = collect_qe_result(
        directory,
        output_name=output_name,
        _allow_label_replacement=True,
    )
    migration = {
        "schema_version": "1.0",
        "migration_id": "qe-positive-compression-to-energy-derivative-stress-v1",
        "run_id": manifest["run_id"],
        "legacy_label_path": str(archive_path),
        "legacy_label_sha256": legacy_sha256,
        "migrated_label_path": str(label_path),
        "migrated_label_sha256": sha256_file(label_path),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "transformation": (
            "stress_gpa_new = -stress_gpa_legacy; legacy values retained as "
            "qe_printed_stress_gpa"
        ),
        "stress_convention": STRESS_CONVENTION,
        "migration_implementation_path": str(Path(__file__).resolve()),
        "migration_implementation_sha256": sha256_file(Path(__file__)),
    }
    migration_path = directory / "dft_label_migration.json"
    atomic_write_json(migration_path, migration)
    return {"label": migrated, "migration": migration}


def _rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def compare_predictions(
    records: Iterable[dict[str, Any]],
    *,
    limits: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compute preregistered CHGNet-versus-DFT validation diagnostics."""
    items = list(records)
    if len(items) < 2:
        raise ValueError("at least two labelled snapshots are required")
    dft_energy = np.array(
        [item["dft"]["total_energy_ev"] / item["n_atoms"] for item in items]
    )
    model_energy = np.array(
        [item["model"]["total_energy_ev"] / item["n_atoms"] for item in items]
    )
    energy_error = (model_energy - model_energy.mean()) - (
        dft_energy - dft_energy.mean()
    )

    force_errors = []
    symbols: list[str] = []
    stress_errors = []
    for item in items:
        dft_force = np.asarray(item["dft"]["forces_ev_angstrom"], dtype=float)
        model_force = np.asarray(item["model"]["forces_ev_angstrom"], dtype=float)
        if dft_force.shape != model_force.shape or dft_force.shape[1:] != (3,):
            raise ValueError("force arrays are not matched N x 3 arrays")
        item_symbols = list(item["symbols"])
        if len(item_symbols) != len(dft_force):
            raise ValueError("force array and symbol counts differ")
        force_errors.append(model_force - dft_force)
        symbols.extend(item_symbols)
        dft_stress = np.asarray(item["dft"]["stress_gpa"], dtype=float)
        model_stress = np.asarray(item["model"]["stress_gpa"], dtype=float)
        if dft_stress.shape != (3, 3) or model_stress.shape != (3, 3):
            raise ValueError("stress tensors must be 3 x 3")
        stress_errors.append(model_stress - dft_stress)

    force = np.concatenate(force_errors, axis=0)
    vector_errors = np.linalg.norm(force, axis=1)
    stress = np.stack(stress_errors)
    element_metrics = {}
    symbol_array = np.asarray(symbols)
    for symbol in sorted(set(symbols)):
        values = force[symbol_array == symbol]
        element_metrics[symbol] = {
            "n_atoms": len(values),
            "component_mae_ev_angstrom": float(np.mean(np.abs(values))),
            "component_rmse_ev_angstrom": _rmse(values),
            "vector_mae_ev_angstrom": float(np.mean(np.linalg.norm(values, axis=1))),
        }
    try:
        from scipy.stats import spearmanr

        rank_correlation = float(spearmanr(dft_energy, model_energy).statistic)
    except ImportError:
        rank_correlation = float("nan")
    metrics = {
        "n_snapshots": len(items),
        "centered_energy_mae_ev_atom": float(np.mean(np.abs(energy_error))),
        "centered_energy_rmse_ev_atom": _rmse(energy_error),
        "relative_energy_spearman": rank_correlation,
        "force_component_mae_ev_angstrom": float(np.mean(np.abs(force))),
        "force_component_rmse_ev_angstrom": _rmse(force),
        "force_component_p95_abs_ev_angstrom": float(np.percentile(np.abs(force), 95)),
        "force_vector_mae_ev_angstrom": float(np.mean(vector_errors)),
        "force_vector_rmse_ev_angstrom": _rmse(vector_errors),
        "stress_component_mae_gpa": float(np.mean(np.abs(stress))),
        "stress_component_rmse_gpa": _rmse(stress),
        "element_resolved_forces": element_metrics,
    }
    if limits is None:
        limits = {
            "centered_energy_mae_ev_atom": 0.015,
            "force_component_mae_ev_angstrom": 0.10,
            "force_component_rmse_ev_angstrom": 0.20,
            "stress_component_mae_gpa": 0.25,
        }
    required_limits = {
        "centered_energy_mae_ev_atom",
        "force_component_mae_ev_angstrom",
        "force_component_rmse_ev_angstrom",
        "stress_component_mae_gpa",
    }
    if set(limits) != required_limits or any(float(value) <= 0 for value in limits.values()):
        raise ValueError("model-domain limits are incomplete or non-positive")
    limits = {name: float(value) for name, value in limits.items()}
    checks = {name: metrics[name] <= limit for name, limit in limits.items()}
    return {
        "schema_version": "1.0",
        "metrics": metrics,
        "preregistered_limits": limits,
        "checks": checks,
        "numerical_gate_pass": all(checks.values()),
        "caveat": (
            "Passing aggregate thresholds does not override temperature-, "
            "configuration-, or element-specific systematic failures."
        ),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    select = subparsers.add_parser("select")
    select.add_argument("protocol")
    select.add_argument("--out", required=True)
    select.add_argument("--project-root", default=".")

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("snapshot_manifest")
    prepare.add_argument("dft_protocol")
    prepare.add_argument("pseudopotential_manifest")
    prepare.add_argument("--pseudo-dir", required=True)
    prepare.add_argument("--out", required=True)
    prepare.add_argument("--qe-executable", default=None)

    collect = subparsers.add_parser("collect")
    collect.add_argument("run_dir")
    collect.add_argument("--output-name", default="pw.out")

    migrate = subparsers.add_parser("migrate-stress-label")
    migrate.add_argument("run_dir")
    migrate.add_argument("--output-name", default="pw.out")
    args = parser.parse_args()

    if args.command == "select":
        result = select_snapshots(
            args.protocol, out_dir=args.out, project_root=args.project_root
        )
    elif args.command == "prepare":
        result = prepare_qe_inputs(
            args.snapshot_manifest,
            args.dft_protocol,
            args.pseudopotential_manifest,
            pseudo_dir=args.pseudo_dir,
            out_dir=args.out,
            qe_executable=args.qe_executable,
        )
    elif args.command == "collect":
        result = collect_qe_result(args.run_dir, output_name=args.output_name)
    else:
        result = migrate_qe_stress_label(
            args.run_dir, output_name=args.output_name
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
