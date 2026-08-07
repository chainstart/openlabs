from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.campaign import load_campaign, run_campaign  # noqa: E402


def _protocol(tmp_path: Path) -> Path:
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "campaign_id": "test-campaign",
                "root_dir": str(tmp_path / "runs"),
                "base_config": {
                    "temperatures": [800],
                    "production_steps": 100,
                    "equilibration_steps": 100,
                    "loginterval": 10,
                },
                "gates": [{"gate_id": "g1", "criterion": "manual review"}],
                "runs": [
                    {
                        "run_id": "pilot-1",
                        "stage": "pilot",
                        "purpose": "test",
                        "enabled": True,
                        "config": {"seed": 7},
                    },
                    {"run_id": "formal-1", "stage": "formal", "enabled": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_campaign_materializes_tuples_and_provenance(tmp_path):
    campaign = load_campaign(_protocol(tmp_path))
    assert campaign.runs[0].config.temperatures == (800,)
    assert campaign.runs[0].config.seed == 7
    assert campaign.runs[0].config.provenance["campaign_run_id"] == "pilot-1"
    assert campaign.runs[0].enabled
    assert not campaign.runs[1].enabled


def test_campaign_runs_enabled_entries_and_checkpoints_state(tmp_path):
    path = _protocol(tmp_path)
    calls = []

    def fake_runner(config, *, run_dir, quiet):
        calls.append((config.seed, Path(run_dir), quiet))
        return {"status": "complete_but_unresolved", "protocol_fingerprint": "fp"}

    state = run_campaign(path, quiet=True, runner=fake_runner)
    assert [item[0] for item in calls] == [7]
    assert state["runs"]["pilot-1"]["status"] == "complete_but_unresolved"
    stored = json.loads((tmp_path / "runs/campaign_state.json").read_text())
    assert stored["runs"]["pilot-1"]["protocol_fingerprint"] == "fp"


def test_explicit_selection_can_run_a_disabled_entry(tmp_path):
    path = _protocol(tmp_path)
    calls = []

    def fake_runner(config, *, run_dir, quiet):
        calls.append(Path(run_dir).name)
        return {"status": "complete_resolved", "protocol_fingerprint": "fp"}

    run_campaign(path, run_ids={"formal-1"}, runner=fake_runner)
    assert calls == ["formal-1"]


def test_unsafe_run_id_is_rejected(tmp_path):
    path = _protocol(tmp_path)
    payload = json.loads(path.read_text())
    payload["runs"][0]["run_id"] = "../escape"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe run_id"):
        load_campaign(path)
