"""Verify saved drug-screen evidence and arithmetic without re-evaluating models."""

import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
import pandas as pd
from verify_checkpoint import WORKSPACE, digest, read


def main():
    project = WORKSPACE / "openlabs-data/workspaces/biology/projects/biomed-drug-support-20261021"
    artifact = WORKSPACE / "openlabs-artifacts/artifact-stage/biomed/drug-support-20261021"
    state = read(project / "research_state.json")
    result = read(project / "results.json")
    verified = []
    for record in [state["plan"], state["environment"], *state["datasets"], *state["evidence"]]:
        path = (project / record["path"]).resolve()
        assert path.is_relative_to(project) and digest(path) == record["sha256"]
        verified.append(record["path"])
    for record in state["datasets"]:
        manifest = read(project / record["path"])
        uri = urlparse(manifest["artifact_uri"])
        path = Path(unquote(uri.path)).resolve()
        assert uri.scheme == "file" and path.is_relative_to(artifact)
        assert path.stat().st_size == manifest["bytes"] < 128 * 1024**2
        assert digest(path) == manifest["sha256"]
    table = project / "samples.csv"
    audit = read(project / "crossed-split-audit.json")
    assert digest(table) == audit["sample_table"]["sha256"]
    samples = pd.read_csv(table)
    assert len(samples) < 100000
    assert not samples.duplicated(["drug_id", "cell_line_id"]).any()
    for column in ("drug_id", "cell_line_id"):
        assert samples.groupby(column)["split"].nunique().max() == 1
    assert samples.groupby("split").size().to_dict() == audit["counts"]
    translation = pd.read_csv(artifact / "translation-by-drug.csv")
    assert len(translation) < 10000
    for record in result["translation_drug_macro"]:
        group = translation[
            (translation.method == record["method"]) & (translation.subset == record["subset"])
        ]
        assert len(group) == record["drugs"]
        assert np.isclose(group.mae.mean(), record["mae"])
    ranks = pd.read_csv(artifact / "rank-support-by-drug.csv")
    ranks = ranks[ranks.support == "own_support"]
    assert len(ranks) == result["counts"]["rank_eligible_drugs"]
    report = {
        "valid": True,
        "metadata_files_verified": verified,
        "raw_payloads_verified": len(state["datasets"]),
        "sample_split_counts": audit["counts"],
        "recomputed_macro_rank_discordance": {
            "support_rule": float(ranks.determined_discordance.mean()),
            "matched_margin": float(ranks.margin_control_discordance.mean()),
            "matched_random": float(ranks.random_control_discordance.mean()),
        },
        "macro_translation_records_checked": len(result["translation_drug_macro"]),
        "models_refitted": False,
        "new_scientific_confirmation": False,
    }
    output = (
        WORKSPACE
        / "openlabs-artifacts/artifact-stage/biomed/campaign-20261021-literature"
        / "drug-checkpoint-verification.json"
    )
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
