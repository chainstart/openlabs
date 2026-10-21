"""Prepare bounded small-molecule CSVs with explicit structure and scaffold identities."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from tools.common import CODE_ROOT, atomic_json, sha256

POLICY = "rdkit-cleanup-fragment-parent-uncharged-canonical-tautomer-isomeric-v1"


def standardize(smiles: str) -> dict:
    from rdkit import Chem, rdBase
    from rdkit.Chem import Descriptors
    from rdkit.Chem.MolStandardize import rdMolStandardize
    from rdkit.Chem.Scaffolds import MurckoScaffold

    if not isinstance(smiles, str) or not smiles.strip() or len(smiles) > 10_000:
        raise ValueError("nonempty SMILES with at most 10000 characters required")
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None or not 1 <= molecule.GetNumAtoms() <= 512:
        raise ValueError("invalid SMILES or molecule outside 1..512 atoms")
    molecule = rdMolStandardize.Cleanup(molecule)
    molecule = rdMolStandardize.FragmentParent(molecule)
    molecule = rdMolStandardize.Uncharger().uncharge(molecule)
    enumerator = rdMolStandardize.TautomerEnumerator()
    enumerator.SetMaxTautomers(100)
    enumerator.SetMaxTransforms(500)
    enumerated = enumerator.Enumerate(molecule)
    if enumerated.status != rdMolStandardize.TautomerEnumeratorStatus.Completed:
        raise ValueError("tautomer enumeration budget exceeded")
    molecule = enumerator.PickCanonical(enumerated)
    canonical = Chem.MolToSmiles(molecule, isomericSmiles=True)
    scaffold = MurckoScaffold.MurckoScaffoldSmiles(mol=molecule, includeChirality=False)
    # Conservatively group all acyclic molecules together rather than treating an empty scaffold
    # as a missing value or silently admitting related acyclic compounds across partitions.
    scaffold = scaffold or "ACYCLIC"
    return {
        "standardized_smiles": canonical,
        "molecule_id": "mol-" + hashlib.sha256(canonical.encode()).hexdigest(),
        "scaffold_id": "scaffold-" + hashlib.sha256(scaffold.encode()).hexdigest(),
        "scaffold_smiles": scaffold,
        "molecular_weight": Descriptors.MolWt(molecule),
        "rdkit_logp": Descriptors.MolLogP(molecule),
        "standardization_policy": POLICY,
        "rdkit_version": rdBase.rdkitVersion,
    }


def prepare(input_csv: Path, output_dir: Path, *, max_rows: int = 10_000) -> dict:
    output_dir = output_dir.resolve()
    if output_dir.is_relative_to(CODE_ROOT) or "openlabs-data" in output_dir.parts:
        raise ValueError("derived tables belong in external artifact staging")
    if max_rows < 1 or input_csv.stat().st_size > 64 * 1024**2:
        raise ValueError("positive row budget and input at most 64 MiB required")
    output_dir.mkdir(parents=True, exist_ok=False)
    accepted, rejected = output_dir / "prepared.csv", output_dir / "rejected.csv"
    counts = {"accepted": 0, "rejected": 0}
    with (
        input_csv.open(newline="", encoding="utf-8-sig") as source,
        accepted.open("x", newline="", encoding="utf-8") as good,
        rejected.open("x", newline="", encoding="utf-8") as bad,
    ):
        reader = csv.DictReader(source)
        fields = reader.fieldnames or []
        derived = [
            "standardized_smiles",
            "molecule_id",
            "scaffold_id",
            "scaffold_smiles",
            "molecular_weight",
            "rdkit_logp",
            "standardization_policy",
            "rdkit_version",
        ]
        if not {"sample_id", "smiles"}.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError("unique sample_id and smiles columns required")
        if set(fields).intersection(derived):
            raise ValueError("input must not contain derived structure columns")
        writer = csv.DictWriter(good, fieldnames=[*fields, *derived])
        writer.writeheader()
        rejected_writer = csv.writer(bad)
        rejected_writer.writerow(["row", "sample_id", "reason"])
        for index, row in enumerate(reader, 1):
            if index > max_rows:
                raise ValueError("row budget exceeded; no completed preparation manifest written")
            try:
                if not row.get("sample_id", "").strip():
                    raise ValueError("missing sample_id")
                converted = standardize(row.get("smiles", ""))
                writer.writerow({**row, **converted})
                counts["accepted"] += 1
            except ValueError as exc:
                rejected_writer.writerow([index, row.get("sample_id"), str(exc)])
                counts["rejected"] += 1
    report = {
        "schema_version": "openlabs.biomed_structure_preparation.v1",
        "valid": counts["accepted"] > 0,
        "counts": counts,
        "policy": POLICY,
        "input": {"uri": input_csv.resolve().as_uri(), "sha256": sha256(input_csv)},
        "prepared": {"path": "prepared.csv", "sha256": sha256(accepted)},
        "rejected": {"path": "rejected.csv", "sha256": sha256(rejected)},
        "limitations": [
            (
                "Fragment-parent/uncharging/tautomer policy is for small-molecule analyses; "
                "audit mixtures, metals and stereochemistry against the scientific question."
            ),
            "All acyclic structures share one conservative scaffold group.",
            "No activity, assay-unit or censoring harmonization is performed by this tool.",
        ],
    }
    atomic_json(output_dir / "preparation.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-rows", default=10_000, type=int)
    args = parser.parse_args()
    try:
        report = prepare(args.input, args.output_dir, max_rows=args.max_rows)
        print(json.dumps(report))
        return int(not report["valid"])
    except (OSError, ValueError, ImportError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
