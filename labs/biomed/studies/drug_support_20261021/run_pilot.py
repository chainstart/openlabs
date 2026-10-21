"""Frozen GDSC concentration-support pilot; run with CPU resource guard."""

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

SEED = 20261021
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda: f.read(1024**2), b""):
            h.update(b)
    return h.hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")


def part(key, axis):
    u = int(hashlib.sha256(f"{SEED}|{axis}|{key}".encode()).hexdigest()[:12], 16) / 16**12
    return "train" if u < 0.6 else "validation" if u < 0.8 else "test"


def xlsx(path):
    """Read one known bounded official workbook without optional Excel packages."""
    with zipfile.ZipFile(path) as z:
        if z.getinfo("xl/worksheets/sheet1.xml").file_size > 1024**3:
            raise ValueError("Unexpected worksheet expansion")
        strings = [
            "".join(e.itertext())
            for e in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)
        ]
        rows = []
        with z.open("xl/worksheets/sheet1.xml") as f:
            for _, e in ET.iterparse(f, events=["end"]):
                if e.tag.endswith("}row"):
                    row = []
                    for c in e:
                        v = c.find("m:v", NS)
                        value = None if v is None else v.text
                        if c.attrib.get("t") == "s":
                            value = strings[int(value)]
                        # Address columns explicitly: absent Excel cells must not shift fields.
                        addr = "".join(a for a in c.attrib["r"] if a.isalpha())
                        idx = 0
                        for a in addr:
                            idx = idx * 26 + ord(a) - 64
                        while len(row) < idx:
                            row.append(None)
                        row[idx - 1] = value
                    rows.append(row)
                    e.clear()
        frame = pd.DataFrame(rows[1:], columns=rows[0])
    return frame


def prepare(root, project):
    ann = pd.read_csv(root / "gdsc-compound-annotations/screened_compounds.csv").fillna("")
    ann["DRUG_ID"] = ann["DRUG_ID"].astype(int)
    conflict = ann.groupby("DRUG_NAME")[["TARGET", "TARGET_PATHWAY"]].nunique().max(axis=1)
    allowed = set(conflict[conflict == 1].index)
    alias_names = {}
    for _, row in ann.iterrows():
        for alias in [row.DRUG_NAME, *str(row.SYNONYMS).split(",")]:
            key = alias.strip().casefold()
            if key:
                alias_names.setdefault(key, set()).add(row.DRUG_NAME)
    alias_conflicts = set().union(*(v for v in alias_names.values() if len(v) > 1))
    allowed -= alias_conflicts
    frames, counts = [], {}
    for i in [1, 2]:
        raw = root / f"gdsc{i}-release85" / f"GDSC{i}_fitted_dose_response_27Oct23.xlsx"
        cache = root / f"gdsc{i}-parsed.parquet"
        df = pd.read_parquet(cache) if cache.exists() else xlsx(raw)
        if not cache.exists():
            df.to_parquet(cache, index=False)
        counts[f"gdsc{i}_raw_rows"] = len(df)
        df["DRUG_ID"] = pd.to_numeric(df["DRUG_ID"], errors="raise").astype(int)
        df = df.merge(
            ann[["DRUG_ID", "DRUG_NAME", "SCREENING_SITE", "TARGET", "TARGET_PATHWAY"]],
            on="DRUG_ID",
            suffixes=("_fit", ""),
            validate="many_to_one",
        )
        df = df[df["DRUG_NAME"].isin(allowed) & df["SANGER_MODEL_ID"].notna()].copy()
        chosen = df.groupby("DRUG_NAME")["DRUG_ID"].min()
        df = df[df["DRUG_ID"] == df["DRUG_NAME"].map(chosen)]
        dup = df.duplicated(["DRUG_NAME", "SANGER_MODEL_ID"], keep=False)
        counts[f"gdsc{i}_duplicate_rows_excluded"] = int(dup.sum())
        df = df[~dup]
        keep = [
            "DRUG_NAME",
            "SANGER_MODEL_ID",
            "DRUG_ID",
            "SCREENING_SITE",
            "MIN_CONC",
            "MAX_CONC",
            "LN_IC50",
            "AUC",
            "RMSE",
        ]
        frames.append(df[keep])
    both = frames[0].merge(
        frames[1], on=["DRUG_NAME", "SANGER_MODEL_ID"], suffixes=("_s", "_t"), validate="one_to_one"
    )
    both["drug_split"] = both["DRUG_NAME"].map(lambda x: part(x, "drug"))
    both["cell_split"] = both["SANGER_MODEL_ID"].map(lambda x: part(x, "cell"))
    counts.update(
        matched_pairs=len(both),
        matched_drugs=both.DRUG_NAME.nunique(),
        matched_cells=both.SANGER_MODEL_ID.nunique(),
        excluded_annotation_conflicts=int((conflict > 1).sum()),
        excluded_alias_conflict_names=sorted(alias_conflicts),
        identity_scope="official_name_groups_not_structure_verified",
    )
    counts["diagonal_counts"] = {
        s: {
            "pairs": int(((both.drug_split == s) & (both.cell_split == s)).sum()),
            "drugs": both.loc[
                (both.drug_split == s) & (both.cell_split == s), "DRUG_NAME"
            ].nunique(),
            "cells": both.loc[
                (both.drug_split == s) & (both.cell_split == s), "SANGER_MODEL_ID"
            ].nunique(),
        }
        for s in ["train", "validation", "test"]
    }
    sample = both[both.drug_split == both.cell_split][
        ["DRUG_NAME", "SANGER_MODEL_ID", "drug_split"]
    ].rename(
        columns={"DRUG_NAME": "drug_id", "SANGER_MODEL_ID": "cell_line_id", "drug_split": "split"}
    )
    sample.insert(0, "sample_id", sample.drug_id + "|" + sample.cell_line_id)
    sample.to_csv(project / "samples.csv", index=False)
    both.to_parquet(root / "paired.parquet", index=False)
    save(root / "identity-audit.json", counts)
    print(json.dumps(counts), flush=True)
    if counts["matched_drugs"] < 20 or counts["matched_cells"] < 100:
        raise ValueError("Insufficient matched identities; feasibility only")
    return both


def interval(y, lo, hi):
    return np.where(y < lo, -np.inf, np.where(y > hi, hi, y)), np.where(
        y > hi, np.inf, np.where(y < lo, lo, y)
    )


def rate(value, mask):
    return float(value[mask].mean()) if mask.any() else None


def rank_audit(df):
    output = []
    for drug, g in df.groupby("DRUG_NAME", sort=True):
        if len(g) < 20:
            continue
        s, t = g.LN_IC50_s.to_numpy(), g.LN_IC50_t.to_numpy()
        ls, hs = np.log(g.MIN_CONC_s.to_numpy()), np.log(g.MAX_CONC_s.to_numpy())
        lt, ht = np.log(g.MIN_CONC_t.to_numpy()), np.log(g.MAX_CONC_t.to_numpy())
        for sensitivity in ["own_support", "intersection_support"]:
            a, b = (
                (ls, hs)
                if sensitivity == "own_support"
                else (np.maximum(ls, lt), np.minimum(hs, ht))
            )
            c, d = (lt, ht) if sensitivity == "own_support" else (a, b)
            if np.any(a > b):
                continue
            lower, upper = interval(s, a, b)
            v, w = interval(t, c, d)
            i, j = np.triu_indices(len(g), 1)
            source_sign, target_sign = np.sign(s[i] - s[j]), np.sign(t[i] - t[j])
            valid = (source_sign != 0) & (target_sign != 0)
            determined = (upper[i] < lower[j]) | (upper[j] < lower[i])
            target_determined = (w[i] < v[j]) | (w[j] < v[i])
            discord = source_sign != target_sign
            n = int(valid.sum())
            nd = int((valid & determined).sum())
            if not n:
                continue
            margin_order = np.flatnonzero(valid)[
                np.argsort(-np.abs(s[i] - s[j])[valid], kind="stable")
            ]
            cellids = g.SANGER_MODEL_ID.to_numpy()
            hashes = np.array(
                [
                    int(
                        hashlib.sha256(
                            f"{SEED}|{drug}|{cellids[x]}|{cellids[y]}".encode()
                        ).hexdigest()[:12],
                        16,
                    )
                    for x, y in zip(i, j, strict=True)
                ],
                dtype=np.int64,
            )
            random_order = np.flatnonzero(valid)[np.argsort(hashes[valid], kind="stable")]
            row = {
                "drug": drug,
                "support": sensitivity,
                "cells": len(g),
                "valid_pairs": n,
                "destination_ties": int((target_sign == 0).sum()),
                "source_ties": int((source_sign == 0).sum()),
                "determined_pairs": nd,
                "ambiguous_pairs": int((valid & ~determined).sum()),
                "determined_fraction": nd / n,
                "point_discordance": rate(discord, valid),
                "determined_discordance": rate(discord, valid & determined),
                "ambiguous_discordance": rate(discord, valid & ~determined),
                "both_determined_discordance": rate(
                    discord, valid & determined & target_determined
                ),
                "both_determined_pairs": int((valid & determined & target_determined).sum()),
                "margin_control_discordance": float(discord[margin_order[:nd]].mean())
                if nd
                else None,
                "random_control_discordance": float(discord[random_order[:nd]].mean())
                if nd
                else None,
                "concordance_outer_lower": int((valid & determined & ~discord).sum()) / n,
                "concordance_outer_upper": int(
                    (valid & determined & ~discord).sum() + (valid & ~determined).sum()
                )
                / n,
            }
            output.append(row)
    return pd.DataFrame(output) if output else pd.DataFrame(columns=["drug", "support"])


def features(df):
    source = df.LN_IC50_s.to_numpy()
    doses = np.log(df[["MIN_CONC_s", "MAX_CONC_s", "MIN_CONC_t", "MAX_CONC_t"]].to_numpy())
    full = np.column_stack(
        [source, df.AUC_s, df.RMSE_s, doses, source - doses[:, 0], source - doses[:, 1]]
    )
    return full, doses


def run(root, project):
    df = pd.read_parquet(root / "paired.parquet")
    numeric = [
        "MIN_CONC_s",
        "MAX_CONC_s",
        "MIN_CONC_t",
        "MAX_CONC_t",
        "LN_IC50_s",
        "AUC_s",
        "RMSE_s",
    ]
    for col in numeric + ["LN_IC50_t"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    ok = np.isfinite(df[numeric]).all(axis=1) & (
        df[["MIN_CONC_s", "MAX_CONC_s", "MIN_CONC_t", "MAX_CONC_t"]] > 0
    ).all(axis=1)
    ok &= (df.MIN_CONC_s <= df.MAX_CONC_s) & (df.MIN_CONC_t <= df.MAX_CONC_t)
    df = df[ok & (df.drug_split == df.cell_split)].copy()
    train = df[(df.drug_split == "train") & np.isfinite(df.LN_IC50_t)].copy()
    xf, xd = features(train)
    y = train.LN_IC50_t.to_numpy()
    models = {
        "affine": LinearRegression().fit(xf[:, :1], y),
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=1)).fit(xf, y),
        "dose_only_ridge": make_pipeline(StandardScaler(), Ridge(alpha=1)).fit(xd, y),
        "hgb": HistGradientBoostingRegressor(
            max_iter=80,
            max_leaf_nodes=15,
            max_depth=4,
            min_samples_leaf=50,
            learning_rate=0.05,
            l2_regularization=1,
            random_state=SEED,
        ).fit(xf, y),
    }
    marker = root / "test-evaluation.started"
    if marker.exists():
        raise ValueError("Test evaluation already started; do not adaptively reuse")
    save(
        root / "frozen-analysis.json",
        {
            "plan_sha256": sha(project / "plan.json"),
            "code_sha256": sha(__file__),
            "fitted_models": list(models),
            "no_tuning": True,
            "test_opened": False,
        },
    )
    marker.write_text("once-only fixed analysis\n")
    test = df[(df.drug_split == "test") & np.isfinite(df.LN_IC50_t)].copy()
    if test.DRUG_NAME.nunique() < 10 or test.SANGER_MODEL_ID.nunique() < 20:
        raise ValueError("Insufficient test identities; feasibility only")
    xf, xd = features(test)
    preds = {
        "identity": test.LN_IC50_s.to_numpy(),
        **{
            k: m.predict(xd if k == "dose_only_ridge" else xf[:, :1] if k == "affine" else xf)
            for k, m in models.items()
        },
    }
    ranks = rank_audit(test)
    ranks.to_csv(root / "rank-support-by-drug.csv", index=False)
    metricrows = []
    supported = (test.LN_IC50_t >= np.log(test.MIN_CONC_t)) & (
        test.LN_IC50_t <= np.log(test.MAX_CONC_t)
    )
    for method, pred in preds.items():
        test["prediction_" + method] = pred
        for support, mask in [
            ("all", np.ones(len(test), dtype=bool)),
            ("destination_supported", supported),
            ("destination_unsupported", ~supported),
        ]:
            e = test.loc[mask, ["DRUG_NAME", "LN_IC50_t"]].copy()
            e["error"] = np.abs(pred[mask] - e.LN_IC50_t)
            for drug, g in e.groupby("DRUG_NAME"):
                idx = g.index
                tau = (
                    kendalltau(test.loc[idx, "prediction_" + method], g.LN_IC50_t).statistic
                    if len(g) >= 3
                    else float("nan")
                )
                metricrows.append(
                    {
                        "method": method,
                        "subset": support,
                        "drug": drug,
                        "n": len(g),
                        "mae": float(g.error.mean()),
                        "within_drug_kendall": float(tau),
                    }
                )
    metrics = pd.DataFrame(metricrows)
    metrics.to_csv(root / "translation-by-drug.csv", index=False)
    test.to_csv(root / "test-predictions.csv.gz", index=False)
    primary = ranks[ranks.support == "own_support"]
    rng = np.random.default_rng(SEED)
    summary = {}
    for col in [
        "determined_fraction",
        "point_discordance",
        "determined_discordance",
        "ambiguous_discordance",
        "both_determined_discordance",
        "margin_control_discordance",
        "random_control_discordance",
        "concordance_outer_lower",
        "concordance_outer_upper",
    ]:
        if col not in primary:
            continue
        values = primary[col].dropna().to_numpy()
        if len(values):
            means = np.mean(rng.choice(values, (1000, len(values)), replace=True), axis=1)
            summary[col] = {
                "drug_macro": float(values.mean()),
                "drugs": len(values),
                "conditional_drug_bootstrap_ci": np.quantile(means, [0.025, 0.975]).tolist(),
            }
    rank_contrasts = []
    for control in ["margin_control_discordance", "random_control_discordance"]:
        if control not in primary:
            continue
        eligible = primary[["determined_discordance", control]].dropna()
        delta = (eligible[control] - eligible.determined_discordance).to_numpy()
        if len(delta):
            means = np.mean(rng.choice(delta, (1000, len(delta)), replace=True), axis=1)
            rank_contrasts.append(
                {
                    "control": control,
                    "support_rule_discordance_reduction": float(delta.mean()),
                    "same_drugs": len(delta),
                    "conditional_drug_bootstrap_ci": np.quantile(means, [0.025, 0.975]).tolist(),
                }
            )
    limitations = [
        "Operational support intervals are not true IC50 bounds, observed censoring, "
        "or confidence intervals",
        "Destination strata use outcome information for retrospective evaluation only",
        "Only paired overlap population; not full library or clinical efficacy",
        "Both historical screens share cell lines and use joint multilevel curve fits; "
        "not raw-sample-blind external validation",
        "Exact official names and target/pathway corroborate compound mapping but "
        "structure identity was not independently verified",
        "Bootstrap conditions on fixed test cell panel and fitted models",
        "Prior art already establishes max-dose bias; novelty and journal suitability "
        "remain unproven",
    ]
    contrasts = []
    for subset, g in metrics.groupby("subset"):
        wide = g.pivot(index="drug", columns="method", values="mae")
        for method in ["identity", "affine", "ridge", "dose_only_ridge"]:
            delta = (wide[method] - wide["hgb"]).dropna().to_numpy()
            if not len(delta):
                continue
            means = np.mean(rng.choice(delta, (1000, len(delta)), replace=True), axis=1)
            contrasts.append(
                {
                    "subset": subset,
                    "comparator": method,
                    "hgb_mae_improvement": float(delta.mean()),
                    "drugs": len(delta),
                    "conditional_drug_bootstrap_ci": np.quantile(means, [0.025, 0.975]).tolist(),
                }
            )
    result = {
        "stage": "exploratory_pilot",
        "paper_candidate": False,
        "identity_scope": "official_drug_name_holdout_not_structure_verified",
        "primary_support_gate": "passed"
        if len(primary) >= 10
        else "feasibility_only_insufficient_rank_eligible_drugs",
        "counts": {
            "train_pairs": len(train),
            "test_pairs": len(test),
            "test_drugs": test.DRUG_NAME.nunique(),
            "test_cells": test.SANGER_MODEL_ID.nunique(),
            "rank_eligible_drugs": len(primary),
        },
        "metrics": summary,
        "paired_rank_control_contrasts": rank_contrasts,
        "translation_drug_macro": [
            {
                "method": m,
                "subset": s,
                "mae": float(g.mae.mean()),
                "within_drug_kendall": float(g.within_drug_kendall.mean())
                if g.within_drug_kendall.notna().any()
                else None,
                "drugs": len(g),
            }
            for (m, s), g in metrics.groupby(["method", "subset"])
        ],
        "paired_translation_contrasts": contrasts,
        "limitations": limitations,
        "run": {
            "seed": SEED,
            "code_sha256": sha(__file__),
            "plan_sha256": sha(project / "plan.json"),
            "environment_sha256": sha(project / "environment.uv.lock"),
        },
    }
    save(root / "results.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--evaluate", action="store_true")
    args = parser.parse_args()
    if args.evaluate:
        run(args.root, args.project)
    else:
        prepare(args.root, args.project)
