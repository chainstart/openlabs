"""Acquire source metadata for candidate pairs, without model selection."""

import hashlib
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd

from tools.dataset_intake import download

ROOT = Path(
    "/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021/chembl37"
)


def main():
    report = json.loads((ROOT / "pair-eligibility.json").read_text())
    ids = sorted(
        {p[k] for t in report["targets"] for p in t["pairs_at_least_40"] for k in ["a", "b"]}
    )
    development = pd.read_csv(ROOT.parent / "pilot-metrics.csv")
    ids = sorted(set(ids) | set(development.assay_a) | set(development.assay_b))
    fields = (
        "assay_chembl_id,target_chembl_id,variant_id,confidence_score,description,assay_type,"
        "bao_format,bao_label,assay_cell_type,assay_tissue,assay_organism,document_chembl_id"
    )
    url = "https://www.ebi.ac.uk/chembl/api/data/assay.json?" + urllib.parse.urlencode(
        {"assay_chembl_id__in": ",".join(ids), "limit": 100, "only": fields}
    )
    suffix = hashlib.sha256(",".join(ids).encode()).hexdigest()[:10]
    dest = ROOT / f"candidate-assay-metadata-{suffix}"
    if not (dest / "manifest.json").exists():
        download(
            source_id="chembl",
            url=url,
            staging_root=ROOT,
            dataset_id=dest.name,
            release_or_accession="ChEMBL37",
            independent_unit="assay metadata",
            terms_url="https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/general-questions",
            reuse_basis="ChEMBL CC BY-SA 3.0; original references retained",
            citation="ChEMBL37 and original assay documents",
            upstream_study_ids=ids,
            filename="data.json",
            max_bytes=2_000_000,
            retries=1,
        )
    payload = json.loads((dest / "data.json").read_text())
    summary = [
        {
            k: r.get(k)
            for k in [
                "assay_chembl_id",
                "target_chembl_id",
                "variant_id",
                "confidence_score",
                "bao_label",
                "assay_cell_type",
                "document_chembl_id",
            ]
        }
        for r in payload["assays"]
    ]
    (ROOT / "candidate-assay-summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
