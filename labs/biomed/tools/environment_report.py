"""Inspect installed package versions/imports without allocating GPU models."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from tools.common import LAB_ROOT, atomic_json, sha256

GROUPS = {
    "core": {
        "numpy": "numpy",
        "scipy": "scipy",
        "pandas": "pandas",
        "pyarrow": "pyarrow",
        "duckdb": "duckdb",
        "httpx": "httpx",
        "scikit-learn": "sklearn",
        "statsmodels": "statsmodels",
        "matplotlib": "matplotlib",
        "pyyaml": "yaml",
        "snakemake": "snakemake",
    },
    "chem": {"rdkit": "rdkit", "xgboost-cpu": "xgboost", "optuna": "optuna"},
    "bulk": {"pydeseq2": "pydeseq2", "gseapy": "gseapy"},
    "singlecell": {"scanpy": "scanpy", "anndata": "anndata", "leidenalg": "leidenalg"},
    "deep": {"scvi-tools": "scvi", "torch": "torch"},
    "census": {"cellxgene-census": "cellxgene_census"},
}


def report(groups: list[str], *, check_imports: bool = True) -> dict:
    active_lock = Path(sys.prefix).parent / "uv.lock"
    results = {}
    for group in groups:
        versions, missing, failures = {}, [], {}
        for package, module in GROUPS[group].items():
            try:
                versions[package] = importlib.metadata.version(package)
                if check_imports:
                    try:
                        importlib.import_module(module)
                    except Exception as exc:
                        failures[package] = f"{type(exc).__name__}: {exc}"
            except importlib.metadata.PackageNotFoundError:
                missing.append(package)
        results[group] = {
            "versions": versions,
            "missing": missing,
            "import_failures": failures,
            "ready": not missing and not failures,
        }
    return {
        "schema_version": "openlabs.biomed_environment.v1",
        "valid": all(item["ready"] for item in results.values()),
        "python": platform.python_version(),
        "executable": sys.executable,
        "groups": results,
        "imports_checked": check_imports,
        "base_lock_sha256": sha256(LAB_ROOT / "uv.lock")
        if (LAB_ROOT / "uv.lock").is_file()
        else None,
        "active_lock": {"path": str(active_lock), "sha256": sha256(active_lock)}
        if active_lock.is_file()
        else None,
        "gpu_workload_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=sorted(GROUPS), action="append", required=True)
    parser.add_argument("--versions-only", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = report(args.group, check_imports=not args.versions_only)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps(result))
    return int(not result["valid"])


if __name__ == "__main__":
    raise SystemExit(main())
