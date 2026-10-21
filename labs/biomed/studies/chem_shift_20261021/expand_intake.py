# ruff: noqa: E501  # Literal provenance URLs and scientific state descriptions.
"""Bounded ChEMBL37 acquisition, eligibility independent of modeling outcomes."""

import concurrent.futures
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.dataset_intake import download

ROOT = Path(
    "/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021/chembl37"
)
TARGETS = [
    "CHEMBL203",
    "CHEMBL204",
    "CHEMBL205",
    "CHEMBL206",
    "CHEMBL214",
    "CHEMBL217",
    "CHEMBL218",
    "CHEMBL219",
    "CHEMBL220",
    "CHEMBL279",
]
FIELDS = "activity_id,assay_chembl_id,molecule_chembl_id,pchembl_value,canonical_smiles,document_chembl_id,standard_type,standard_units,standard_relation,data_validity_comment,potential_duplicate,target_chembl_id,assay_type,assay_description"


def acquire(dataset_id, url):
    p = ROOT / dataset_id / "manifest.json"
    if p.exists():
        return json.loads((p.parent / "data.json").read_text())
    download(
        source_id="chembl",
        url=url,
        staging_root=ROOT,
        dataset_id=dataset_id,
        release_or_accession="ChEMBL37; verify status before and after acquisition",
        independent_unit="compound-assay measurement",
        terms_url="https://chembl.gitbook.io/chembl-interface-documentation/frequently-asked-questions/general-questions",
        reuse_basis="ChEMBL CC BY-SA 3.0; retain source release and author attribution",
        citation="ChEMBL37, database paper and original document identifiers retained in payload",
        upstream_study_ids=["ChEMBL37; original document identifiers in payload"],
        filename="data.json",
        max_bytes=8_000_000,
        retries=2,
    )
    return json.loads((ROOT / dataset_id / "data.json").read_text())


def target(target):
    query = {
        "target_chembl_id": target,
        "standard_type": "IC50",
        "standard_relation": "=",
        "standard_units": "nM",
        "pchembl_value__isnull": "false",
        "limit": 1000,
        "only": FIELDS,
    }
    base = "https://www.ebi.ac.uk/chembl/api/data/activity.json?"
    first = acquire(f"{target.lower()}-page-000", base + urllib.parse.urlencode(query))
    total = first["page_meta"]["total_count"]
    if total > 30000:
        return {
            "target": target,
            "status": "over_prespecified_30000_record_cap",
            "total": total,
            "pages": 1,
        }
    rows = first["activities"]
    for offset in range(1000, total, 1000):
        q = {**query, "offset": offset}
        page = acquire(
            f"{target.lower()}-page-{offset // 1000:03}", base + urllib.parse.urlencode(q)
        )
        assert page["page_meta"]["total_count"] == total, "Source changed during acquisition"
        rows.extend(page["activities"])
    assert len(rows) == total
    (ROOT / f"{target}-activities.json").write_text(json.dumps(rows))
    result = {
        "target": target,
        "status": "acquired",
        "total": total,
        "pages": (total + 999) // 1000,
    }
    print(json.dumps(result), flush=True)
    return result


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    plan = {
        "targets": TARGETS,
        "endpoint": "exact IC50 nM, non-null pchembl",
        "record_cap_per_target": 30000,
        "page_limit": 1000,
        "max_page_bytes": 8000000,
        "selection": "fixed target list before modeling, no outcome-based selection",
        "resource_budget": {"cpu_threads": 2, "memory_mib": 1536, "scratch_mib": 512},
    }
    (ROOT / "acquisition-plan.json").write_text(json.dumps(plan, indent=2))
    status = acquire("status-before", "https://www.ebi.ac.uk/chembl/api/data/status.json")
    assert "37" in str(status.get("chembl_db_version"))
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        for future in concurrent.futures.as_completed([pool.submit(target, t) for t in TARGETS]):
            try:
                results.append(future.result())
            except Exception as e:
                results.append({"status": "failed", "error": str(e)})
                print(str(e), flush=True)
            (ROOT / "acquisition-progress.json").write_text(json.dumps(results, indent=2))
    after = acquire("status-after", "https://www.ebi.ac.uk/chembl/api/data/status.json")
    assert status["chembl_db_version"] == after["chembl_db_version"]
    (ROOT / "acquisition-results.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
