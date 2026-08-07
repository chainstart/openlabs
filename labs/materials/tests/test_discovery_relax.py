from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones
from ase.io import write

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.discovery_relax import (
    assess_model_agreement,
    load_relaxation_protocol,
    run_relaxation_campaign,
)
from matfactory.provenance import fingerprint, sha256_file

TEMPLATE = ROOT / "analysis/protocols/hidden_order_dual_relaxation_v1.json"


def _campaign(tmp_path: Path) -> Path:
    orderings = []
    for index, distance in enumerate((2.2, 2.5, 2.9)):
        atoms = Atoms(
            "Ar2",
            positions=[[0, 0, 0], [distance, 0, 0]],
            cell=[8, 8, 8],
            pbc=True,
        )
        path = tmp_path / f"ordering-{index}.cif"
        write(path, atoms)
        orderings.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "n_atoms": 2,
            }
        )
    ordering_manifest = {
        "content_fingerprint": "a" * 64,
        "results": [{"candidate_id": "argon", "orderings": orderings}],
    }
    ordering_path = tmp_path / "orderings.json"
    ordering_path.write_text(json.dumps(ordering_manifest), encoding="utf-8")
    artifacts = []
    for family in ("family-a", "family-b"):
        artifact = tmp_path / f"{family}.model"
        artifact.write_bytes(family.encode())
        artifacts.append(
            {
                "model_id": family,
                "family": family,
                "artifact_path": str(artifact),
                "artifact_sha256": sha256_file(artifact),
            }
        )
    registry = {"content_fingerprint": "b" * 64, "models": artifacts}
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    payload = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    payload.update(
        {
            "relaxation_id": "test-relax-v1",
            "root_dir": str(tmp_path / "run"),
            "enabled": True,
            "ordering_manifest": str(ordering_path),
            "approved_ordering_content_fingerprint": "a" * 64,
            "model_registry": str(registry_path),
            "approved_registry_content_fingerprint": "b" * 64,
            "device": "cpu",
        }
    )
    payload["optimizer"].update({"fmax_ev_a": 100.0, "max_steps": 200})
    payload["budget"].update(
        {"wall_time_hours": 1, "gpu_hours": 1, "estimated_minutes_per_job": 1}
    )
    protocol = tmp_path / "protocol.json"
    protocol.write_text(json.dumps(payload), encoding="utf-8")
    return protocol


def test_frozen_relaxation_protocol_is_disabled():
    protocol = load_relaxation_protocol(TEMPLATE)
    assert not protocol.enabled
    with pytest.raises(RuntimeError, match="disabled"):
        run_relaxation_campaign(TEMPLATE)


def test_dual_model_campaign_runs_and_resumes(tmp_path):
    protocol = _campaign(tmp_path)
    factories = {
        "family-a": lambda _record: LennardJones(epsilon=0.8, sigma=2.0),
        "family-b": lambda _record: LennardJones(epsilon=1.0, sigma=2.0),
    }
    first = run_relaxation_campaign(protocol, calculator_factories=factories)
    second = run_relaxation_campaign(protocol, calculator_factories=factories)
    assert len(first["jobs"]) == 6
    assert all(job["status"] == "completed" for job in first["jobs"])
    assert first["jobs"] == second["jobs"]
    candidate = first["agreement"]["candidates"][0]
    assert candidate["n_paired"] == 3
    assert candidate["screen_passed"]


def test_agreement_uses_rank_not_cross_model_energy_scale():
    rows = []
    structures = {}
    for family, energies in (("a", [1.0, 2.0, 3.0]), ("b", [101.0, 102.0, 103.0])):
        for index, energy in enumerate(energies):
            ordering_id = f"x--{index:03d}"
            rows.append(
                {
                    "status": "completed",
                    "converged": True,
                    "candidate_id": "x",
                    "ordering_id": ordering_id,
                    "model_family": family,
                    "final_energy_ev_atom": energy,
                }
            )
            structures[(family, ordering_id)] = Atoms(
                "He", positions=[[0, 0, 0]], cell=[5, 5, 5], pbc=True
            )
    report = assess_model_agreement(
        rows,
        structures,
        {
            "minimum_pairs": 3,
            "minimum_spearman": 0.9,
            "top_k": 1,
            "minimum_top_k_overlap": 1.0,
            "maximum_median_rmsd_angstrom": 0.01,
            "maximum_median_cell_strain": 0.01,
        },
    )
    assert report["candidates"][0]["spearman_rank_correlation"] == pytest.approx(1)
    assert report["candidates"][0]["within_model_energy_spread_mev_atom"] == {
        "a": pytest.approx(2000),
        "b": pytest.approx(2000),
    }
    assert report["candidates"][0]["screen_passed"]
    assert fingerprint(report)


def test_budget_rejects_materialized_jobs(tmp_path):
    protocol = _campaign(tmp_path)
    payload = json.loads(protocol.read_text(encoding="utf-8"))
    payload["budget"]["gpu_hours"] = 0.01
    protocol.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="above frozen budget"):
        run_relaxation_campaign(
            protocol,
            calculator_factories={
                "family-a": lambda _record: LennardJones(),
                "family-b": lambda _record: LennardJones(),
            },
        )


def test_campaign_can_filter_frozen_ordering_manifest(tmp_path):
    protocol = _campaign(tmp_path)
    payload = json.loads(protocol.read_text(encoding="utf-8"))
    ordering_path = Path(payload["ordering_manifest"])
    ordering_manifest = json.loads(ordering_path.read_text(encoding="utf-8"))
    duplicate = dict(ordering_manifest["results"][0])
    duplicate["candidate_id"] = "excluded"
    ordering_manifest["results"].append(duplicate)
    ordering_path.write_text(json.dumps(ordering_manifest), encoding="utf-8")
    payload["included_candidate_ids"] = ["argon"]
    protocol.write_text(json.dumps(payload), encoding="utf-8")

    result = run_relaxation_campaign(
        protocol,
        calculator_factories={
            "family-a": lambda _record: LennardJones(epsilon=0.8, sigma=2.0),
            "family-b": lambda _record: LennardJones(epsilon=1.0, sigma=2.0),
        },
    )

    assert len(result["jobs"]) == 6
    assert result["included_candidate_ids"] == ["argon"]
    assert {job["candidate_id"] for job in result["jobs"]} == {"argon"}
