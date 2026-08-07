from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.dft_decision import choose_adjacent_setting  # noqa: E402
from matfactory.provenance import sha256_file  # noqa: E402


def _settings(ecut: int) -> dict:
    return {
        "ecutwfc_ry": ecut,
        "ecutrho_ry": ecut * 8,
        "kpoints": "gamma",
        "conv_thr_ry": 1e-8,
        "electron_maxstep": 250,
        "mixing_mode": "plain",
        "mixing_beta": 0.3,
        "diagonalization": "david",
    }


def _report(
    tmp_path: Path,
    protocol: Path,
    name: str,
    lower: dict,
    upper: dict,
    passed: bool,
) -> Path:
    path = tmp_path / f"{name}.json"
    payload = {
        "comparison_kind": "qe-numerical-convergence",
        "protocol_sha256": sha256_file(protocol),
        "numerically_converged": passed,
        "metrics": {"example": 1.0},
        "checks": {"example": passed},
        "records": [
            {"lower": {"settings": lower}, "upper": {"settings": upper}},
            {"lower": {"settings": lower}, "upper": {"settings": upper}},
        ],
    }
    path.write_text(json.dumps(payload))
    return path


def test_cutoff_decision_chooses_lowest_passing_lower_setting(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text("{}\n")
    first = _report(
        tmp_path, protocol, "75-90", _settings(75), _settings(90), False
    )
    second = _report(
        tmp_path, protocol, "90-105", _settings(90), _settings(105), True
    )
    decision = choose_adjacent_setting(
        [first, second], stage="cutoff", protocol_path=protocol
    )
    assert decision["can_continue"] is True
    assert decision["selected_settings"]["ecutwfc_ry"] == 90
    assert decision["selected_comparison_index"] == 1
    assert decision["selection_is_model_blind"] is True


def test_decision_rejects_broken_ladder_or_nonstage_change(tmp_path):
    protocol = tmp_path / "protocol.json"
    protocol.write_text("{}\n")
    first = _report(
        tmp_path, protocol, "75-90", _settings(75), _settings(90), False
    )
    broken_lower = _settings(105)
    second = _report(
        tmp_path, protocol, "105-120", broken_lower, _settings(120), True
    )
    with pytest.raises(ValueError, match="continuous ladder"):
        choose_adjacent_setting(
            [first, second], stage="cutoff", protocol_path=protocol
        )

    changed = _settings(90)
    changed["conv_thr_ry"] = 1e-10
    bad = _report(tmp_path, protocol, "bad", _settings(75), changed, True)
    with pytest.raises(ValueError, match="non-stage settings"):
        choose_adjacent_setting([bad], stage="cutoff", protocol_path=protocol)
