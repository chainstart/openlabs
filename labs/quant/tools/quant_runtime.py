#!/usr/bin/env python3
"""Inspect the isolated Quant Lab environment without downloading data or trading."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

RUNTIME_SCHEMA = "openlabs.quant_runtime.v1"
CORE_PACKAGES = (
    "arch",
    "duckdb",
    "exchange-calendars",
    "numpy",
    "pandas",
    "polars",
    "pyarrow",
    "scikit-learn",
    "scipy",
    "statsmodels",
)
RESEARCH_PACKAGES = (
    "cvxpy",
    "lightgbm",
    "mlflow",
    "optuna",
    "pyqlib",
    "vectorbt",
    "xgboost",
)
EXECUTION_PACKAGES = ("ccxt", "nautilus-trader")
RUNTIME_PROBE_PACKAGES = {"cvxpy", "pyqlib", "vectorbt", "nautilus-trader"}
IMPORT_MODULES = {
    "arch": "arch",
    "duckdb": "duckdb",
    "exchange-calendars": "exchange_calendars",
    "numpy": "numpy",
    "pandas": "pandas",
    "polars": "polars",
    "pyarrow": "pyarrow",
    "scikit-learn": "sklearn",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
    "cvxpy": "cvxpy",
    "lightgbm": "lightgbm",
    "mlflow": "mlflow",
    "optuna": "optuna",
    "pyqlib": "qlib",
    "vectorbt": "vectorbt",
    "xgboost": "xgboost",
    "ccxt": "ccxt",
    "nautilus-trader": "nautilus_trader",
}


def package_versions(
    python: Path, names: tuple[str, ...]
) -> tuple[dict[str, str], list[str]]:
    if python.resolve() != Path(sys.executable).resolve():
        script = """
import importlib.metadata
import json
import sys

versions = {}
missing = []
for name in json.loads(sys.argv[1]):
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        missing.append(name)
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

    versions: dict[str, str] = {}
    missing: list[str] = []
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    return versions, missing


def import_failures(python: Path, names: tuple[str, ...]) -> dict[str, str]:
    modules = {name: IMPORT_MODULES[name] for name in names}
    if python.resolve() == Path(sys.executable).resolve():
        failures: dict[str, str] = {}
        for name, module in modules.items():
            try:
                importlib.import_module(module)
            except Exception as exc:  # noqa: BLE001 - runtime audit records the exact import failure.
                failures[name] = f"{type(exc).__name__}: {exc}"[:500]
        return failures

    script = """
import importlib
import json
import sys

failures = {}
for name, module in json.loads(sys.argv[1]).items():
    try:
        importlib.import_module(module)
    except Exception as exc:
        failures[name] = f"{type(exc).__name__}: {exc}"[:500]
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


def report(
    lab_root: Path, *, import_names: set[str] | None = None
) -> dict[str, object]:
    lab_python = lab_root.resolve() / ".venv" / "bin" / "python"
    python = lab_python if lab_python.is_file() else Path(sys.executable).resolve()
    import_names = import_names or set()
    groups: dict[str, object] = {}
    for group, names in (
        ("core", CORE_PACKAGES),
        ("research", RESEARCH_PACKAGES),
        ("execution", EXECUTION_PACKAGES),
    ):
        versions, missing = package_versions(python, names)
        probe = tuple(name for name in names if name in import_names)
        failures = import_failures(python, probe) if probe and not missing else {}
        groups[group] = {
            "versions": versions,
            "missing": missing,
            "import_failures": failures,
            "imports_verified": list(probe),
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
        "lab_root": str(lab_root.resolve()),
        "lock_present": (lab_root / "uv.lock").is_file(),
        "groups": groups,
        "safety": {
            "live_trading_enabled": False,
            "broker_credentials_required": False,
            "network_data_download_performed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "prepare", "doctor"))
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--agent-workspace", type=Path)
    parser.add_argument("--artifacts-root", type=Path)
    args = parser.parse_args()

    if args.command == "prepare":
        import_names = RUNTIME_PROBE_PACKAGES
    elif args.command == "doctor":
        import_names = set(IMPORT_MODULES)
    else:
        import_names = set()
    payload = report(args.lab_root, import_names=import_names)
    if args.command == "prepare":
        if args.agent_workspace is None or args.artifacts_root is None:
            payload["valid"] = False
            payload["errors"] = ["prepare requires --agent-workspace and --artifacts-root"]
        else:
            args.agent_workspace.resolve().mkdir(parents=True, exist_ok=True)
            (args.artifacts_root.resolve() / "experiments").mkdir(parents=True, exist_ok=True)
            payload["runtime_paths"] = {
                "agent_workspace": str(args.agent_workspace.resolve()),
                "experiments_root": str(args.artifacts_root.resolve() / "experiments"),
            }
            required_ready = all(
                payload["groups"][group]["ready"] for group in ("core", "research")
            )
            if not required_ready:
                payload["valid"] = False
                payload["errors"] = [
                    "Quant core/research environment is incomplete; run "
                    "uv sync --all-groups in labs/quant"
                ]
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
