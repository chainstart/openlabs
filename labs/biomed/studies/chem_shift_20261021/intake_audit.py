# ruff: noqa: E501  # Literal provenance URLs and scientific state descriptions.
"""Acquire the author-published assay corpus and audit feasibility, not outcomes."""

import concurrent.futures
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.dataset_intake import download

ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021")
ROOT.mkdir(parents=True, exist_ok=True)


def main():
    with urllib.request.urlopen(
        "https://api.github.com/repos/rinikerlab/overlapping_assays/git/trees/main?recursive=1",
        timeout=45,
    ) as r:
        tree = json.load(r)
    (ROOT / "upstream-tree.json").write_text(json.dumps(tree, indent=2))
    with urllib.request.urlopen(
        "https://api.github.com/repos/rinikerlab/overlapping_assays/commits/main", timeout=45
    ) as r:
        commit_record = json.load(r)
    (ROOT / "upstream-commit.json").write_text(json.dumps(commit_record, indent=2))
    commit = commit_record["sha"]
    # The observed tree endpoint may echo the symbolic commit resolution rather
    # than the root tree ID. Verify every downloaded blob below independently.
    files = [
        x
        for x in tree["tree"]
        if x["path"].startswith("datasets/source_data/") and x["path"].endswith(".IC50.csv.gz")
    ]
    assert len(files) < 150 and sum(x["size"] for x in files) < 5_000_000
    base = f"https://raw.githubusercontent.com/rinikerlab/overlapping_assays/{commit}/"

    def intake(item):
        name = item["path"].split("/")[-1]
        dest = ROOT / name.replace(".", "-")
        if not (dest / "manifest.json").exists():
            download(
                source_id="riniker_overlapping_assays",
                url=base + item["path"],
                staging_root=ROOT,
                dataset_id=dest.name,
                release_or_accession=f"ChEMBL32; author git tree {commit}",
                independent_unit="molecule-assay measurement",
                terms_url="https://github.com/rinikerlab/overlapping_assays/blob/main/LICENSE",
                reuse_basis="Author code MIT; underlying ChEMBL32 data CC BY-SA 3.0; retain attribution and source metadata",
                citation="Landrum and Riniker 2024, DOI 10.1021/acs.jcim.4c00049",
                upstream_study_ids=[
                    "ChEMBL32",
                    "original publication identifiers not supplied in derived CSV; must recover before source-level inference",
                ],
                filename="data.csv.gz",
                max_bytes=1_000_000,
                retries=1,
            )
        df = pd.read_csv(dest / "data.csv.gz")
        payload = (dest / "data.csv.gz").read_bytes()
        blob_sha = hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()
        assert blob_sha == item["sha"], f"Git blob mismatch for {name}"
        target = name.split("-")[0].replace("target_", "")
        grouped = (
            df.groupby(["assay_chembl_id", "compound_chembl_id"]).pchembl_value.median().unstack(0)
        )
        pairs = []
        cols = list(grouped.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1 :]:
                common = grouped[[a, b]].dropna()
                if len(common) >= 20:
                    pairs.append({"a": a, "b": b, "n_common": len(common)})
        return {
            "file": name,
            "target": target,
            "rows": len(df),
            "molecules": df.compound_chembl_id.nunique(),
            "assays": len(cols),
            "eligible_pairs": pairs,
        }

    reports = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for f in concurrent.futures.as_completed([pool.submit(intake, x) for x in files]):
            try:
                result = f.result()
                reports.append(result)
                print(
                    json.dumps(
                        {"file": result["file"], "eligible_pairs": len(result["eligible_pairs"])}
                    ),
                    flush=True,
                )
            except Exception as e:
                reports.append({"error": str(e)})
    (ROOT / "feasibility.json").write_text(
        json.dumps(
            {
                "commit": commit,
                "root_tree_sha": commit_record["commit"]["tree"]["sha"],
                "tree_endpoint_sha": tree["sha"],
                "blob_verification": "git SHA1 verified for every acquired file",
                "files": reports,
            },
            indent=2,
        )
    )
    print(
        json.dumps(
            {
                "files": len(reports),
                "eligible_pairs": sum(len(x.get("eligible_pairs", [])) for x in reports),
                "targets": len({x["target"] for x in reports if x.get("eligible_pairs")}),
            }
        )
    )


if __name__ == "__main__":
    main()
