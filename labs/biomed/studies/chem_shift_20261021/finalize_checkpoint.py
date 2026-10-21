# ruff: noqa: E501  # Literal scientific state descriptions retained as auditable sentences.
"""Preserve the no-go checkpoint and stop claiming a worker remains active."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.common import atomic_json
from tools.dataset_intake import validate_manifest

HERE = Path(__file__).resolve().parent
ART = Path("/home/biostar/work/openlabs-artifacts/artifact-stage/biomed/chem-shift-20261021")
DEST = Path(
    "/home/biostar/work/openlabs-data/workspaces/biology/projects/biomed-chem-shift-20261021"
)


def record(path):
    return {
        "path": str(path.relative_to(DEST)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    manifests = []
    (DEST / "intake-manifests").mkdir(exist_ok=True)
    for source in sorted(ART.glob("**/manifest.json")):
        manifest = json.loads(source.read_text())
        errors = validate_manifest(manifest, verify_payload=True)
        assert not errors, (source, errors)
        target = DEST / "intake-manifests" / f"{manifest['dataset_id']}.json"
        target.write_bytes(source.read_bytes())
        manifests.append(record(target))
    results = json.loads((ART / "chembl37/acquisition-results.json").read_text())
    pairs = json.loads((ART / "chembl37/pair-eligibility.json").read_text())
    summary = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "status": "needs_replan",
        "paper_candidate": False,
        "chembl37_fixed_targets": len(results),
        "chembl37_measurements": sum(r.get("total", 0) for r in results),
        "all_intake_payloads_verified": len(manifests),
        "pairs_ge40": sum(len(t["pairs_at_least_40"]) for t in pairs["targets"]),
        "cross_document_pairs_ge40": sum(
            p["cross_document"] for t in pairs["targets"] for p in t["pairs_at_least_40"]
        ),
        "scientific_decision": "No-go for a publication-ready cross-assay translation claim with this corpus",
        "reasons": [
            "Development pilot has near-identical paired values and offers no useful adaptation evidence",
            "Broader fixed-target cohort yields only two cross-document pairs with >=40 shared compounds; biological comparability remains unresolved",
            "Assay-type B includes different biological endpoints; metadata/source independence is not established by an ID",
            "Closest literature already covers basic assay transition, matched-pair noise, assay curation and scaffold conformal prediction",
        ],
        "untouched_holdout": "The original ChEMBL32 five reserved targets were not modeled. Expanded ChEMBL37 cohort is exploratory provenance data, not an untouched confirmatory cohort.",
        "label_dependent_screening": "Near-equality uses both labels as candidate duplicate diagnostics, not outcome-blind eligibility or proof of recitation. Raw data retained.",
        "workers_running": False,
        "next_required_step": "Select or acquire genuinely independent paired assay campaigns and freeze a new plan including source-potency and joint anchor controls; do not reuse exploratory cohorts as confirmatory",
    }
    atomic_json(ART / "checkpoint.json", summary)
    evidence = []
    for src, name in [
        (ART / "checkpoint.json", "checkpoint.json"),
        (ART / "chembl37/pair-eligibility.json", "expanded-pair-eligibility.json"),
        (ART / "chembl37/candidate-assay-summary.json", "candidate-assay-summary.json"),
        (ART / "pilot-results.json", "development-pilot-results.json"),
    ]:
        target = DEST / name
        target.write_bytes(src.read_bytes())
        evidence.append(record(target))
    state = json.loads((DEST / "research_state.json").read_text())
    state.update(
        status="needs_replan",
        factory_startup="paused; direct guarded workers completed; no background continuation scheduled",
        datasets=manifests,
        evidence=evidence,
        next_experiment=summary["next_required_step"],
        worker={"running": False, "reason": "Actual acquisition and metadata workers completed"},
        claims=[
            {
                "status": "provisional",
                "text": "The acquired paired-activity cohorts do not yet support a publication-ready cross-assay adaptation claim; no confirmation was performed.",
            }
        ],
    )
    atomic_json(DEST / "research_state.json", state)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
