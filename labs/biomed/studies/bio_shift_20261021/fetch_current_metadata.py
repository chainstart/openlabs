"Retrieve bounded, identity-only official CMP metadata; no assay measurements."

import hashlib
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.dataset_intake import download, validate_manifest  # noqa: E402

ROOT = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/bio-shift-20261021")


def main():
    page = 1
    pages = 1
    count = None
    models = []
    manifests = []
    while page <= pages:
        params = {
            "page[size]": 500,
            "page[number]": page,
            "include": "identifiers,sample",
            "fields[model]": "names,identifiers,parent,sample",
            "fields[sample]": "patient",
        }
        url = "https://api.cellmodelpassports.sanger.ac.uk/models?" + urlencode(params)
        dataset_id = f"cmp-current-models-page-{page}"
        manifest_path = ROOT / dataset_id / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            errors = validate_manifest(manifest, verify_payload=True)
            if errors:
                raise ValueError(errors)
        else:
            manifest = download(
                source_id="projectscore",
                url=url,
                staging_root=ROOT,
                dataset_id=dataset_id,
                release_or_accession="official CMP API identity snapshot retrieved 2026-10-21",
                independent_unit="cell_line",
                terms_url="https://www.sanger.ac.uk/tool/project-score-database/",
                reuse_basis=(
                    "Official public model identity/parent/sample-to-patient mapping;"
                    " internal research use; no unrestricted redistribution assumed"
                ),
                citation=(
                    "Cell Model Passports doi:10.1093/nar/gky872; Project Score "
                    "doi:10.1093/nar/gkaa882; access 2026-10-21"
                ),
                upstream_study_ids=["official-cell-model-passports-identity-registry"],
                filename="identities.json",
                max_bytes=4 * 1024**2,
                retries=2,
            )
        payload = json.loads((ROOT / dataset_id / "identities.json").read_text())
        if count is None:
            count = payload["meta"]["count"]
            if count > 3000:
                raise ValueError("More than 3000 models exceeds metadata budget")
            pages = math.ceil(count / 500)
        elif count != payload["meta"]["count"]:
            raise ValueError("Metadata count changed during pagination")
        included = {(item["type"], str(item["id"])): item for item in payload["included"]}
        for model in payload["data"]:
            relationships = model["relationships"]
            identifiers = [
                included[(item["type"], str(item["id"]))]["attributes"]["identifier"]
                for item in relationships["identifiers"]["data"]
            ]
            sample_ref = relationships["sample"]["data"]
            sample = included[(sample_ref["type"], str(sample_ref["id"]))] if sample_ref else None
            patient = sample["relationships"]["patient"]["data"] if sample else None
            parent = relationships["parent"]["data"]
            models.append(
                {
                    "model_id": model["id"],
                    "names": model["attributes"]["names"],
                    "identifiers": identifiers,
                    "sample_id": sample_ref["id"] if sample_ref else None,
                    "patient_id": patient["id"] if patient else None,
                    "parent_id": parent["id"] if parent else None,
                }
            )
        manifests.append(
            {
                "path": str(manifest_path),
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "payload_sha256": manifest["sha256"],
                "models": len(payload["data"]),
            }
        )
        print(
            json.dumps({"page": page, "pages": pages, "models": len(payload["data"])}), flush=True
        )
        page += 1
    if len(models) != count or len({model["model_id"] for model in models}) != count:
        raise ValueError("Pagination missing or duplicated models")
    (ROOT / "current-cmp-identities.json").write_text(
        json.dumps(
            {
                "source": "official CMP API",
                "count": count,
                "manifests": manifests,
                "models": models,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
