"""Frozen cross-laboratory replication-risk pilot. CPU only, two threads.

All target-label access is masked by independently frozen gene and cell axes.
"""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 20261021


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def axis_part(value, axis):
    v = int(hashlib.sha256(f"{SEED}|{axis}|{value}".encode()).hexdigest()[:12], 16) / 16**12
    return 0 if v < 0.6 else 1 if v < 0.8 else 2


def load_matrix(path):
    # Original files are numeric gene-by-cell matrices. Preserve exact IDs.
    frame = pd.read_csv(path, sep="\t", index_col=0)
    frame.index = frame.index.astype(str)
    frame.columns = frame.columns.astype(str)
    if frame.index.has_duplicates or frame.columns.has_duplicates:
        raise ValueError("Duplicate matrix identifiers")
    return frame


def metric(error, score, informative, coverage):
    ids = np.flatnonzero(informative)
    tie = np.random.default_rng(SEED).random(len(score))
    order = ids[np.lexsort((tie[ids], score[ids]))]
    keep = order[: max(1, math.ceil(len(order) * coverage))]
    return float(error[keep].mean()), keep


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--inspect-only", action="store_true")
    args = p.parse_args()
    root, project = args.root, args.project
    if not args.inspect_only and (root / "test-evaluation.started").exists():
        raise ValueError("Frozen test was already opened; no adaptive rerun permitted")
    paths = [root / "broad/corrected_logFCs.tsv", root / "sanger/01_corrected_logFCs.tsv"]
    source, target = [load_matrix(path) for path in paths]
    mapping_path = root / "author-cell-mapping/mapping.tsv"
    mapping = pd.read_csv(mapping_path, sep="\t", index_col=0)
    if (
        mapping.index.has_duplicates
        or mapping["BROAD_ID"].duplicated().any()
        or mapping["model_name"].duplicated().any()
    ):
        raise ValueError("Ambiguous author cell identity mapping")
    broad_map = {row.BROAD_ID: sidm for sidm, row in mapping.iterrows()}
    sanger_map = {row.model_name: sidm for sidm, row in mapping.iterrows()}
    source = source.loc[:, source.columns.isin(broad_map)].rename(columns=broad_map)
    target = target.loc[:, target.columns.isin(sanger_map)].rename(columns=sanger_map)
    ids = {
        "source_shape": source.shape,
        "target_shape": target.shape,
        "source_genes_head": source.index[:4].tolist(),
        "target_genes_head": target.index[:4].tolist(),
        "source_cells_head": source.columns[:6].tolist(),
        "target_cells_head": target.columns[:6].tolist(),
    }
    print(json.dumps(ids), flush=True)
    genes = sorted(set(source.index) & set(target.index))
    cells = sorted(set(source.columns) & set(target.columns))
    ids.update(shared_genes=len(genes), shared_cells=len(cells))
    (root / "identity-audit.json").write_text(json.dumps(ids, indent=2) + "\n")
    if args.inspect_only:
        return
    if len(genes) < 5000 or len(cells) < 60:
        raise ValueError("Insufficient exact-matched identities; replan before labels")
    gp = np.array([axis_part(g, "gene") for g in genes])
    cp = np.array([axis_part(c, "cell") for c in cells])
    # Persist axes before numeric outcomes are used. Both IDs remain exact strings.
    pd.DataFrame({"gene_id": genes, "split": np.array(["train", "validation", "test"])[gp]}).to_csv(
        project / "gene-splits.csv", index=False
    )
    pd.DataFrame(
        {"cell_line_id": cells, "split": np.array(["train", "validation", "test"])[cp]}
    ).to_csv(project / "cell-splits.csv", index=False)
    x = source.loc[genes, cells].to_numpy(dtype=np.float32)
    # Target labels are only extracted within diagonal blocks below.
    gene_mean = np.nanmean(x[:, cp == 0], axis=1)
    gene_sd = np.nanstd(x[:, cp == 0], axis=1)
    gene_q10 = np.nanquantile(x[:, cp == 0], 0.1, axis=1)
    gene_q90 = np.nanquantile(x[:, cp == 0], 0.9, axis=1)
    cell_mean = np.nanmean(x[gp == 0], axis=0)
    cell_sd = np.nanstd(x[gp == 0], axis=0)
    sd_cut = np.quantile(gene_sd[gp == 0], 0.75)
    strong_cut = np.nanquantile(x[np.ix_(gp == 0, cp == 0)], 0.1)
    if not np.isfinite(sd_cut) or not np.isfinite(strong_cut):
        raise ValueError(
            "Missing source descriptors violate predeclared threshold definition; replan"
        )
    rng = np.random.default_rng(SEED)

    def block(part):
        gi, ci = np.where(gp == part)[0], np.where(cp == part)[0]
        g, c = np.meshgrid(gi, ci, indexing="ij")
        g, c = g.ravel(), c.ravel()
        value = x[g, c]
        y = target.loc[np.array(genes)[gi], np.array(cells)[ci]].to_numpy(dtype=np.float32).ravel()
        z = value - gene_mean[g]
        features = np.column_stack(
            [
                value,
                gene_mean[g],
                gene_sd[g],
                gene_q10[g],
                gene_q90[g],
                cell_mean[c],
                cell_sd[c],
                z,
                z / np.maximum(gene_sd[g], 1e-5),
            ]
        ).astype(np.float32)
        ok = np.isfinite(features).all(axis=1) & np.isfinite(y)
        informative = (gene_sd[g] > sd_cut) & (value < gene_mean[g] - gene_sd[g])
        return {
            "features": features[ok],
            "y": y[ok],
            "g": g[ok],
            "c": c[ok],
            "informative": informative[ok],
            "strong_effect": value[ok] < strong_cut,
            "source": value[ok],
        }

    train = block(0)
    # Fixed cap chosen prospectively, before training outcomes.
    select = rng.choice(len(train["y"]), min(200000, len(train["y"])), replace=False)
    cal = LinearRegression().fit(train["source"][select, None], train["y"][select])
    train_error = np.abs(train["y"] - cal.predict(train["source"][:, None]))
    risk_y = np.log1p(train_error[select])
    ridge = make_pipeline(StandardScaler(), Ridge(alpha=10)).fit(train["features"][select], risk_y)
    hgb = HistGradientBoostingRegressor(
        max_iter=80,
        max_leaf_nodes=15,
        max_depth=4,
        min_samples_leaf=100,
        learning_rate=0.05,
        l2_regularization=1,
        random_state=SEED,
    ).fit(train["features"][select], risk_y)

    def score_block(data):
        f = data["features"]
        return {
            "deterministic_random": rng.random(len(f)),
            "absolute_source_effect": np.abs(f[:, 0]),
            "gene_standard_deviation": f[:, 2],
            "absolute_source_contrast": np.abs(f[:, 7]),
            "ridge_risk": ridge.predict(f),
            "hgb_risk": hgb.predict(f),
        }

    validation = block(1)
    if (
        len(set(validation["g"][validation["informative"]])) < 20
        or len(set(validation["c"][validation["informative"]])) < 10
    ):
        raise ValueError("Informative validation too small; stop before test outcomes")
    verror = np.abs(validation["y"] - cal.predict(validation["source"][:, None]))
    vscores = score_block(validation)
    signs, validation_metrics = {}, {}
    for name, score in vscores.items():
        if not np.isfinite(score).all():
            raise ValueError(f"Nonfinite validation risk scores: {name}")
        options = (
            [1, -1]
            if name
            in {"absolute_source_effect", "gene_standard_deviation", "absolute_source_contrast"}
            else [1]
        )
        sign = min(
            options, key=lambda s: metric(verror, score * s, validation["informative"], 0.5)[0]
        )
        signs[name] = sign
        validation_metrics[name] = metric(verror, score * sign, validation["informative"], 0.5)[0]
    simple = [
        "deterministic_random",
        "absolute_source_effect",
        "gene_standard_deviation",
        "absolute_source_contrast",
    ]
    best = min(simple, key=validation_metrics.get)
    frozen_selection = {
        "selection_time_unix": time.time(),
        "best_simple_baseline": best,
        "signs": signs,
        "validation_informative_mae50": validation_metrics,
        "affine_slope": float(cal.coef_[0]),
        "affine_intercept": float(cal.intercept_),
        "source_gene_sd_cut": float(sd_cut),
        "source_strong_effect_cut": float(strong_cut),
        "test_target_labels_evaluated": False,
    }
    (root / "frozen-model-selection.json").write_text(json.dumps(frozen_selection, indent=2) + "\n")
    if (root / "test-evaluation.started").exists():
        raise ValueError("Refusing adaptive re-evaluation of frozen test outcomes")
    (root / "test-evaluation.started").write_text(str(time.time()) + "\n")
    test = block(2)
    if (
        len(set(test["g"][test["informative"]])) < 20
        or len(set(test["c"][test["informative"]])) < 10
    ):
        raise ValueError("Informative holdout too small; do not promote")
    scores = {name: score * signs[name] for name, score in score_block(test).items()}
    error = np.abs(test["y"] - cal.predict(test["source"][:, None]))
    raw_error = np.abs(test["y"] - test["source"])
    masks = {
        "all": np.ones(len(error), dtype=bool),
        "informative": test["informative"],
        "strong_effect": test["strong_effect"],
    }
    rows, selected = [], {}
    for subset, mask in masks.items():
        for name, score in scores.items():
            for coverage in [0.25, 0.5, 0.75, 1.0]:
                value, keep = metric(error, score, mask, coverage)
                rows.append(
                    {
                        "subset": subset,
                        "method": name,
                        "coverage": coverage,
                        "mae": value,
                        "raw_mae_same_selected": float(raw_error[keep].mean()),
                        "n_pairs": len(keep),
                        "n_genes": len(set(test["g"][keep])),
                        "n_cells": len(set(test["c"][keep])),
                        "informative_fraction": float(test["informative"][keep].mean()),
                    }
                )
                if subset == "informative" and coverage == 0.5:
                    selected[name] = keep
    pd.DataFrame(rows).to_csv(root / "risk-coverage.csv", index=False)
    # Product-weight (pigeonhole) bootstrap respects both independent axes.
    ng, nc = len(genes), len(cells)
    tg, tc = np.where(gp == 2)[0], np.where(cp == 2)[0]
    diffs = []
    ridge_diffs = []
    for _ in range(500):
        gw = np.bincount(rng.choice(tg, len(tg), replace=True), minlength=ng)
        cw = np.bincount(rng.choice(tc, len(tc), replace=True), minlength=nc)
        weight = gw[test["g"]] * cw[test["c"]]
        values = []
        for name in [best, "hgb_risk", "ridge_risk"]:
            k = selected[name]
            values.append(
                float(np.average(error[k], weights=weight[k])) if weight[k].sum() else float("nan")
            )
        diffs.append(values[0] - values[1])
        ridge_diffs.append(values[2] - values[1])
    point = (
        metric(error, scores[best], test["informative"], 0.5)[0]
        - metric(error, scores["hgb_risk"], test["informative"], 0.5)[0]
    )
    ci = np.nanquantile(diffs, [0.025, 0.975]).tolist()
    ridge_point = (
        metric(error, scores["ridge_risk"], test["informative"], 0.5)[0]
        - metric(error, scores["hgb_risk"], test["informative"], 0.5)[0]
    )
    ridge_ci = np.nanquantile(ridge_diffs, [0.025, 0.975]).tolist()
    predictions = pd.DataFrame(
        {
            "gene_id": np.array(genes)[test["g"]],
            "cell_line_id": np.array(cells)[test["c"]],
            "source": test["source"],
            "target": test["y"],
            "calibrated_absolute_error": error,
            "informative": test["informative"],
            **scores,
        }
    )
    predictions.to_csv(root / "test-predictions.csv.gz", index=False)
    result = {
        "stage": "exploratory_pilot",
        "independent_unit": "gene_and_cell_line_crossed",
        "metrics": {
            "informative_mae50_improvement_hgb_over_validation_best_simple": point,
            "improvement_ci_low": ci[0],
            "improvement_ci_high": ci[1],
            "informative_mae50_improvement_hgb_over_ridge": ridge_point,
            "ridge_comparison_ci_low": ridge_ci[0],
            "ridge_comparison_ci_high": ridge_ci[1],
        },
        "positive_pilot_signal": bool(ci[0] > 0),
        "paper_candidate": False,
        "baselines": validation_metrics,
        "trials_run": 2,
        "sample_counts": {
            "shared_genes": len(genes),
            "shared_cells": len(cells),
            "train_pairs": len(train["y"]),
            "training_pairs_used": len(select),
            "validation_pairs": len(validation["y"]),
            "test_pairs": len(test["y"]),
            "test_informative_pairs": int(test["informative"].sum()),
            "test_genes": len(tg),
            "test_cells": len(tc),
        },
        "limitations": [
            "Only two historical laboratories; no unseen-laboratory validation",
            "Source profiling of all test genes/cells is available by design",
            "Gene/cell crossed independence is approximate; related cell lines may share donors",
            "Pilot holdout is not independent prospective confirmation",
            "No guide-level mechanism or therapeutic efficacy claim",
            "Prior-art search uses primary web sources; scholarly MCP unavailable",
        ],
        "run": {
            "seed": SEED,
            "code_sha256": sha(Path(__file__)),
            "environment_sha256": sha(project / "environment.uv.lock"),
            "plan_sha256": sha(project / "plan.json"),
            "input_sha256": {str(path): sha(path) for path in paths},
        },
        "selected_simple": best,
        "selection_file_sha256": sha(root / "frozen-model-selection.json"),
    }
    result["run"]["mapping_sha256"] = sha(mapping_path)
    result["run"]["preprocessing_addendum_sha256"] = sha(project / "preprocessing-addendum.json")
    result["metric_scope"] = (
        "Pair-weighted MAE within prespecified source-informative subset; "
        "confidence intervals condition on frozen retained policies and resample "
        "both gene and cell axes."
    )
    (root / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
