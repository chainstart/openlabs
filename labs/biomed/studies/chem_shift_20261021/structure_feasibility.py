"""Metadata-only eligibility: endpoint provenance and distinct scaffold support."""

import json
from pathlib import Path

import pandas as pd
from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021")


def main():
    report = json.loads((ROOT / "feasibility.json").read_text())
    out = []
    for record in report["files"]:
        if not record.get("eligible_pairs"):
            continue
        frame = pd.read_csv(ROOT / record["file"].replace(".", "-") / "data.csv.gz")
        for pair in record["eligible_pairs"]:
            sub = frame[frame.assay_chembl_id.isin([pair["a"], pair["b"]])]
            common = sub.groupby("compound_chembl_id").filter(
                lambda g: g.assay_chembl_id.nunique() == 2
            )
            unique = common.drop_duplicates("compound_chembl_id")
            scaffolds = []
            for smiles in unique.canonical_smiles:
                mol = Chem.MolFromSmiles(smiles)
                scaffolds.append(
                    MurckoScaffold.MurckoScaffoldSmiles(mol=mol) if mol is not None else "INVALID"
                )
            counts = pd.Series(scaffolds).value_counts()
            out.append(
                dict(
                    target=record["target"],
                    file=record["file"],
                    **pair,
                    n_scaffolds=len(counts),
                    scaffold_sizes=counts.tolist(),
                )
            )
    (ROOT / "structure-feasibility.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
