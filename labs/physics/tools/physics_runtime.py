#!/usr/bin/env python3
"""Inspect the isolated Physics Lab environment without downloading data."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

RUNTIME_SCHEMA = "openlabs.physics_runtime.v1"
GROUPS = {
    "core": (
        "h5py",
        "httpx",
        "matplotlib",
        "mpmath",
        "numpy",
        "pandas",
        "pint",
        "pydantic",
        "python-flint",
        "pyyaml",
        "scipy",
        "sympy",
        "uncertainties",
        "xarray",
    ),
    "optimization": ("clarabel", "cvxpy", "scs"),
    "quantum": ("qutip",),
    "astro": ("astropy", "gwosc"),
    "hep": ("awkward", "hist", "iminuit", "particle", "pyhf", "uproot", "vector"),
}
IMPORT_MODULES = {name: name.replace("-", "_") for names in GROUPS.values() for name in names}
IMPORT_MODULES.update({"python-flint": "flint", "pyyaml": "yaml"})
PREPARE_PROBES = {"astropy", "cvxpy", "numpy", "pyhf", "qutip", "sympy", "uproot"}


def _package_versions(python: Path, names: tuple[str, ...]) -> tuple[dict[str, str], list[str]]:
    script = """
import importlib.metadata, json, sys
versions, missing = {}, []
for name in json.loads(sys.argv[1]):
    try: versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError: missing.append(name)
print(json.dumps({"versions": versions, "missing": missing}, sort_keys=True))
"""
    completed = subprocess.run(
        [str(python), "-c", script, json.dumps(names)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(completed.stdout)
    return dict(payload["versions"]), list(payload["missing"])


def _import_failures(python: Path, names: tuple[str, ...]) -> dict[str, str]:
    modules = {name: IMPORT_MODULES[name] for name in names}
    if python.resolve() == Path(sys.executable).resolve():
        failures: dict[str, str] = {}
        for name, module in modules.items():
            try:
                importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001 - doctor reports exact failures.
                failures[name] = f"{type(exc).__name__}: {exc}"[:500]
        return failures
    script = """
import importlib, json, sys
failures = {}
for name, module in json.loads(sys.argv[1]).items():
    try: importlib.import_module(module)
    except Exception as exc: failures[name] = f"{type(exc).__name__}: {exc}"[:500]
print(json.dumps(failures, sort_keys=True))
"""
    completed = subprocess.run(
        [str(python), "-c", script, json.dumps(modules)],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    lines = completed.stdout.strip().splitlines()
    return dict(json.loads(lines[-1])) if lines else {"runtime": "import probe emitted no JSON"}


def report(lab_root: Path, *, import_names: set[str] | None = None) -> dict[str, object]:
    lab_root = lab_root.resolve()
    lab_python = lab_root / ".venv" / "bin" / "python"
    python = lab_python if lab_python.is_file() else Path(sys.executable).resolve()
    import_names = import_names or set()
    groups: dict[str, object] = {}
    for group, names in GROUPS.items():
        versions, missing = _package_versions(python, names)
        probes = tuple(name for name in names if name in import_names and name not in missing)
        failures = _import_failures(python, probes) if probes else {}
        groups[group] = {
            "versions": versions,
            "missing": missing,
            "imports_verified": list(probes),
            "import_failures": failures,
            "ready": not missing and not failures,
        }
    python_version = subprocess.run(
        [str(python), "-c", "import platform; print(platform.python_version())"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    return {
        "schema_version": RUNTIME_SCHEMA,
        "valid": True,
        "errors": [],
        "python": {
            "executable": str(python),
            "version": python_version or platform.python_version(),
            "isolated_lab_environment": python == lab_python,
        },
        "lab_root": str(lab_root),
        "lock_present": (lab_root / "uv.lock").is_file(),
        "groups": groups,
        "safety": {
            "physical_experiment_execution_enabled": False,
            "instrument_control_enabled": False,
            "public_data_download_performed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "prepare", "doctor"))
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--agent-workspace", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    args = parser.parse_args()
    probes = PREPARE_PROBES if args.command == "prepare" else set(IMPORT_MODULES)
    if args.command == "inspect":
        probes = set()
    payload = report(args.lab_root, import_names=probes)
    if args.command == "doctor":
        incomplete = [name for name, group in payload["groups"].items() if not group["ready"]]
        if incomplete:
            payload["valid"] = False
            payload["errors"] = [f"incomplete physics environment groups: {', '.join(incomplete)}"]
    if args.command == "prepare":
        if args.agent_workspace is None or args.artifacts_root is None:
            payload["valid"] = False
            payload["errors"] = ["prepare requires --agent-workspace and --artifacts-root"]
        else:
            args.agent_workspace.resolve().mkdir(parents=True, exist_ok=True)
            experiments = args.artifacts_root.resolve() / "experiments"
            experiments.mkdir(parents=True, exist_ok=True)
            payload["runtime_paths"] = {
                "agent_workspace": str(args.agent_workspace.resolve()),
                "experiments_root": str(experiments),
            }
            if not payload["groups"]["core"]["ready"]:
                payload["valid"] = False
                payload["errors"] = [
                    "Physics core environment is incomplete; run "
                    "bin/openlabs-resource-guard -- uv sync --all-groups in labs/physics"
                ]
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
