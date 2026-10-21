"""Download a tiny ChEMBL structure subset and compute descriptors, not research claims."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from tools.common import LAB_ROOT, atomic_json, read_json, sha256
from tools.dataset_intake import download, source_record


def run(staging_root: Path) -> dict:
    from rdkit import Chem, rdBase
    from rdkit.Chem import Descriptors, rdFingerprintGenerator
    from rdkit.Chem.Scaffolds import MurckoScaffold

    source = source_record("chembl")
    metadata = dict(
        source_id="chembl",
        staging_root=staging_root,
        independent_unit="molecule",
        terms_url=source["terms_url"],
        reuse_basis=source["reuse_basis"],
        citation="ChEMBL official API; exact release recorded below; infrastructure smoke only",
        upstream_study_ids=["not-applicable: structure-only infrastructure check"],
        max_bytes=2 * 1024**2,
        filename="data.json",
    )
    download(
        **metadata,
        url=source["api_base"] + "status.json",
        dataset_id="chembl-status-before",
        release_or_accession="API status at retrieval",
    )
    before = read_json(staging_root / "chembl-status-before/data.json")
    release = before.get("chembl_db_version")
    if not isinstance(release, str) or not release:
        raise ValueError("ChEMBL API did not supply a database version")
    # A fixed reference record avoids a database-wide sort and keeps the smoke bounded.
    url = source["api_base"] + "molecule/CHEMBL25.json"
    manifest = download(
        **metadata, url=url, dataset_id="chembl-molecules", release_or_accession=release
    )
    download(
        **metadata,
        url=source["api_base"] + "status.json",
        dataset_id="chembl-status-after",
        release_or_accession=release,
    )
    after = read_json(staging_root / "chembl-status-after/data.json")
    if after.get("chembl_db_version") != release:
        raise ValueError("ChEMBL release changed during acquisition; discard/retry this smoke")
    reference = read_json(staging_root / "chembl-molecules/data.json")
    if reference.get("molecule_chembl_id") != "CHEMBL25":
        raise ValueError("unexpected ChEMBL reference molecule")
    records = [reference]
    output = staging_root / "descriptors.csv"
    count = 0
    skipped = []
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)
    with output.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "molecule_id",
                "canonical_smiles",
                "scaffold",
                "molecular_weight",
                "rdkit_logp",
                "morgan_on_bits",
            ]
        )
        for record in records:
            structures = record.get("molecule_structures") or {}
            molecule = Chem.MolFromSmiles(structures.get("canonical_smiles", ""))
            if molecule is None or molecule.GetNumAtoms() == 0:
                skipped.append(record["molecule_chembl_id"])
                continue
            writer.writerow(
                [
                    record["molecule_chembl_id"],
                    Chem.MolToSmiles(molecule),
                    MurckoScaffold.MurckoScaffoldSmiles(mol=molecule),
                    Descriptors.MolWt(molecule),
                    Descriptors.MolLogP(molecule),
                    generator.GetFingerprint(molecule).GetNumOnBits(),
                ]
            )
            count += 1
    if count < 1:
        raise ValueError("no usable chemical structures retrieved")
    report = {
        "schema_version": "openlabs.biomed_live_smoke.v1",
        "valid": True,
        "purpose": "Infrastructure verification only; no prediction, biological finding or paper",
        "chembl_release": release,
        "molecules_received": len(records),
        "descriptor_rows": count,
        "skipped_molecule_ids": skipped,
        "rdkit_version": rdBase.rdkitVersion,
        "input_manifest": {
            "path": "chembl-molecules/manifest.json",
            "sha256": sha256(staging_root / "chembl-molecules/manifest.json"),
        },
        "payload_sha256": manifest["sha256"],
        "descriptors": {"path": "descriptors.csv", "sha256": sha256(output)},
        "environment": {"path": str(LAB_ROOT / "uv.lock"), "sha256": sha256(LAB_ROOT / "uv.lock")},
    }
    atomic_json(staging_root / "smoke-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.staging_root.resolve())))
        return 0
    except (OSError, ValueError, KeyError, ImportError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
