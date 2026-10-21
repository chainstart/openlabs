"""Audit stored evidence and preserve a negative frozen pilot without promotion."""

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021")
PROJECT = Path(
    "/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-bio-shift-20261021"
)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(path, obj):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def ref(name):
    return {"path": name, "sha256": sha(PROJECT / name)}


def main():
    result = json.loads((ROOT / "results.json").read_text())
    if result["paper_candidate"] or result["positive_pilot_signal"]:
        raise ValueError("This report is specific to the observed negative pilot")
    provenance = []
    for source in ["broad", "sanger"]:
        path = ROOT / source / "member-manifest.json"
        manifest = json.loads(path.read_text())
        member = manifest["extracted_member"]
        assert sha(Path(member["path"])) == member["sha256"]
        for record in manifest["downloaded_ranges"]:
            assert sha(Path(record["path"])) == record["sha256"]
        provenance.append(
            {
                "source": source,
                "manifest_sha256": sha(path),
                "member_sha256": member["sha256"],
                "range_hashes_verified": len(manifest["downloaded_ranges"]),
                "crc32_validated": member["crc32_validated"],
                "full_archive_downloaded": False,
            }
        )
    audit = {
        "schema_version": "openlabs.biomed_crossed_axes_audit.v1",
        "axes": {},
        "target_label_rule": (
            "Only diagonal train, validation, test blocks are used; "
            "off-diagonal target labels unused"
        ),
        "source_profile_rule": (
            "Full source matrix is profiling data; gene statistics fit only train "
            "cells; cell statistics fit only train genes"
        ),
        "provenance": provenance,
    }
    for axis, col in [("gene", "gene_id"), ("cell", "cell_line_id")]:
        frame = pd.read_csv(PROJECT / f"{axis}-splits.csv")
        assert not frame[col].duplicated().any()
        sets = {
            split: set(frame.loc[frame["split"] == split, col])
            for split in ["train", "validation", "test"]
        }
        overlaps = {
            f"{a}-{b}": len(sets[a] & sets[b])
            for a, b in [("train", "validation"), ("train", "test"), ("validation", "test")]
        }
        assert not any(overlaps.values())
        audit["axes"][axis] = {
            "sample_table": ref(f"{axis}-splits.csv"),
            "counts": {k: len(v) for k, v in sets.items()},
            "overlap_counts": overlaps,
        }
    audit["valid"] = True
    dump(PROJECT / "crossed-axis-audit.json", audit)
    risk = pd.read_csv(ROOT / "risk-coverage.csv")
    pooled = risk[(risk["subset"] == "all") & (risk["coverage"] == 0.5)].set_index("method")
    informative = risk[(risk["subset"] == "informative") & (risk["coverage"] == 0.5)].set_index(
        "method"
    )
    h = pooled.loc["hgb_risk"]
    retained = round(float(h["n_pairs"]) * float(h["informative_fraction"]))
    secondary = {
        "hgb_pooled_mae50": float(h["mae"]),
        "random_pooled_mae50": float(pooled.loc["deterministic_random", "mae"]),
        "pooled_relative_error_reduction_vs_random": 1
        - float(h["mae"]) / float(pooled.loc["deterministic_random", "mae"]),
        "retained_pairs": int(h["n_pairs"]),
        "retained_informative_pairs": retained,
        "informative_pairs_total": result["sample_counts"]["test_informative_pairs"],
        "fraction_of_informative_pairs_retained": retained
        / result["sample_counts"]["test_informative_pairs"],
        "informative_mae50": informative["mae"].to_dict(),
        "interpretation": (
            "Pooled error reduction substantially depletes source-defined "
            "context-specific signal. This is a prespecified secondary diagnostic, "
            "not a replacement primary outcome or a new-paper novelty claim."
        ),
    }
    dump(PROJECT / "secondary-diagnostics.json", secondary)
    for source in ["broad", "sanger"]:
        shutil.copyfile(
            ROOT / source / "member-manifest.json",
            PROJECT / f"{source}-archive-member-manifest.json",
        )
    shutil.copyfile(
        ROOT / "author-cell-mapping/manifest.json", PROJECT / "cell-mapping-intake-manifest.json"
    )
    shutil.copyfile(ROOT / "results.json", PROJECT / "results.json")
    shutil.copyfile(ROOT / "frozen-model-selection.json", PROJECT / "frozen-model-selection.json")
    shutil.copyfile(ROOT / "identity-audit.json", PROJECT / "identity-audit.json")
    dump(
        PROJECT / "software-validation.json",
        {
            "synthetic_data": True,
            "scientific_result": False,
            "runs": 2,
            "heldout_target_label_change_does_not_change_selection": True,
            "description": (
                "Changing only synthetic test target outcomes by +100 preserved all "
                "frozen train/validation selection values except clock timestamp. Both "
                "children inherited openlabs-workers.slice."
            ),
        },
    )
    artifacts = []
    for name in [
        "results.json",
        "risk-coverage.csv",
        "test-predictions.csv.gz",
        "frozen-model-selection.json",
        "test-evaluation.started",
    ]:
        artifacts.append(
            {
                "artifact_uri": (ROOT / name).as_uri(),
                "bytes": (ROOT / name).stat().st_size,
                "sha256": sha(ROOT / name),
            }
        )
    dump(PROJECT / "artifact-index.json", {"artifacts": artifacts, "raw_payloads": provenance})
    state = json.loads((PROJECT / "research_state.json").read_text())
    state.update(
        status="needs_replan",
        paper_candidate=False,
        next_experiment=(
            "Stop adaptive tuning on this consumed holdout. Independent scientific "
            "review must determine whether a distinct hypothesis and untouched "
            "dataset justify a new study; this pilot does not support a "
            "publication-ready claim."
        ),
        completed_at_utc=datetime.now(UTC).isoformat(),
        worker_status=(
            "No live research worker: bounded pilot finished; factory startup remains paused."
        ),
        protocol_status=(
            "NOT PASSED: current generic validator does not support crossed-axis "
            "independent unit/split strategy or selected archive-member range "
            "intake. Additional explicit crossed-axis and provenance audits passed."
        ),
        datasets=[ref("cell-mapping-intake-manifest.json")],
        evidence=[
            ref(name)
            for name in [
                "results.json",
                "crossed-axis-audit.json",
                "secondary-diagnostics.json",
                "artifact-index.json",
                "identity-audit.json",
                "software-validation.json",
                "broad-archive-member-manifest.json",
                "sanger-archive-member-manifest.json",
                "protocol-validation.json",
                "literature-audit.json",
                "preprocessing-addendum.json",
            ]
        ],
        claims=[
            {
                "status": "provisional",
                "text": (
                    "This pilot did not detect a bootstrap-supported HGB gain in "
                    "informative-subset MAE@50% against the selected simple baseline "
                    "or Ridge. Intervals crossing zero do not establish equivalence "
                    "or rule out a useful gain."
                ),
            },
            {
                "status": "provisional",
                "text": (
                    "The prespecified pooled-risk diagnostic selected only 48 of 2792 "
                    "source-defined informative pairs at 50% total-pair retention, despite "
                    "reducing pooled MAE."
                ),
            },
        ],
    )
    if (PROJECT / "continuation-decision.json").exists():
        for name in [
            "continuation-decision.json",
            "fresh-cell-metadata.csv",
            "fresh-cell-metadata-audit.json",
            "current-fresh-cell-metadata.csv",
            "current-fresh-cell-audit.json",
        ]:
            state["evidence"].append(ref(name))
        metadata_dir = PROJECT / "metadata-intakes"
        metadata_dir.mkdir(exist_ok=True)
        for number in range(1, 6):
            name = f"cmp-current-models-page-{number}"
            shutil.copyfile(ROOT / name / "manifest.json", metadata_dir / f"{name}.json")
            state["datasets"].append(ref(f"metadata-intakes/{name}.json"))
        state["next_experiment"] = (
            "Current-data paper development is no-go after primary-source novelty "
            "and official metadata audit. Only four analytically unused cell lines "
            "remain. Preserve their target values; acquire a genuinely unused cohort "
            "and predeclare a distinct hypothesis before further confirmation."
        )
    dump(PROJECT / "research_state.json", state)
    print(
        json.dumps(
            {
                "state": state["status"],
                "paper_candidate": False,
                "axis_audit_valid": True,
                "secondary": secondary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
