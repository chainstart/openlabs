"""Verify sparse single-cell analysis with synthetic counts; no scientific claim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.common import LAB_ROOT, atomic_json, sha256


def run() -> dict:
    import anndata
    import numpy as np
    import scanpy as sc
    from scipy import sparse

    rng = np.random.default_rng(0)
    adata = anndata.AnnData(sparse.csr_matrix(rng.poisson(2, size=(128, 64))))
    adata.layers["counts"] = adata.X.copy()
    sc.pp.normalize_total(adata, target_sum=10_000)
    sc.pp.log1p(adata)
    sc.pp.pca(adata, n_comps=8, random_state=0)
    sc.pp.neighbors(adata, n_neighbors=5, n_pcs=8, method="gauss", random_state=0)
    sc.tl.leiden(adata, flavor="igraph", directed=False, n_iterations=2, random_state=0)
    if adata.obsm["X_pca"].shape != (128, 8) or adata.obs["leiden"].isna().any():
        raise ValueError("single-cell software smoke failed")
    return {
        "schema_version": "openlabs.biomed_singlecell_smoke.v1",
        "valid": True,
        "synthetic_software_smoke": True,
        "scientific_result": False,
        "cells": adata.n_obs,
        "genes": adata.n_vars,
        "pca_components": 8,
        "cluster_count": int(adata.obs["leiden"].nunique()),
        "count_layer_preserved": sparse.issparse(adata.layers["counts"]),
        "lock_sha256": sha256(LAB_ROOT / "environments/singlecell/uv.lock"),
        "code_sha256": sha256(Path(__file__)),
        "gpu_workload_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run()
        atomic_json(args.output, result)
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
