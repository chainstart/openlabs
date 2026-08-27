from __future__ import annotations

import json
import shutil
from pathlib import Path

from protocols.quant_research_protocol import validate
from tools.quant_runtime import report
from tools.trial_ledger import validate_ledger

LAB_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = LAB_ROOT / "protocols" / "examples"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_example_protocol_passes_discovery_and_commit() -> None:
    project = EXAMPLES / "project.json"
    state = EXAMPLES / "research_state.json"
    assert validate(project, state, mode="discovery") == []
    assert validate(project, state, mode="commit") == []


def test_commit_replays_frozen_input_hash(tmp_path: Path) -> None:
    fixture = tmp_path / "examples"
    shutil.copytree(EXAMPLES, fixture)
    (fixture / "frozen_input.json").write_text("changed\n", encoding="utf-8")
    errors = validate(fixture / "project.json", fixture / "research_state.json", mode="commit")
    assert any("does not match the frozen input" in error for error in errors)


def test_confirmation_trial_fails_closed_without_holdout_controls() -> None:
    ledger = _read(EXAMPLES / "trial_ledger.json")
    ledger["trials"][0]["stage"] = "confirmation"
    errors = validate_ledger(
        ledger,
        project_id="quant-example",
        workstream_id="example-factor",
    )
    assert any("selection_locked" in error for error in errors)
    assert any("holdout_access" in error for error in errors)
    assert any("multiplicity_family_size" in error for error in errors)


def test_runtime_inspection_is_safe_without_optional_groups() -> None:
    payload = report(LAB_ROOT)
    assert payload["valid"] is True
    assert payload["safety"] == {
        "live_trading_enabled": False,
        "broker_credentials_required": False,
        "network_data_download_performed": False,
    }
