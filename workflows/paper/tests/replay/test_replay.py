"""Replay of about 100 archived unified-review decisions (B6, 2026-11-25).

The fixture ``decisions.json.gz`` holds the synthesis inputs of each decision (role reports,
formal findings, follow-up items, changed text excerpts); ``replay_lib.replay`` recomputes the
merged decision with the current code. Two checks:

* the cases named in the 2026-11-23 convergence audit decide as the audit says
  (``expectations.json``);
* no other verdict drifts silently: every decision's outcome and set of blocking items match
  ``expected_verdicts.json``. After a reviewed rule change, regenerate it with
  ``python tests/replay/run_replay.py --write-expected`` and record the change list
  (``compare.py``) in the change's maintenance note.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay_lib import EXPECTATIONS, EXPECTED, digest, load_fixture, replay, snapshot_key, verdicts  # noqa: E402


@pytest.fixture(scope="module")
def replayed():
    return {snapshot_key(snap): verdicts(replay(snap)) for snap in load_fixture()}


def test_fixture_covers_about_one_hundred_decisions(replayed):
    assert 90 <= len(replayed) <= 130


@pytest.mark.parametrize("case", json.loads(EXPECTATIONS.read_text())["cases"], ids=lambda c: c["label"][:60])
def test_audit_cases(replayed, case):
    result = replayed[case["decision"]]
    if "outcome" in case:
        assert result["outcome"] == case["outcome"], case["label"]
    if "outcome_not" in case:
        assert result["outcome"] != case["outcome_not"], case["label"]
    for item in case.get("items", []):
        prefix = f"{item.get('kind', 'change')}|{item['role']}|"
        matches = {key: value for key, value in result["items"].items()
                   if key.startswith(prefix) and item["contains"] in key}
        assert matches, f"{case['label']}: no item containing {item['contains']!r}"
        # A blocking finding may also be echoed as advice (a follow-up's plain dimension text);
        # an advisory one must never block anywhere.
        if item["verdict"] == "block":
            assert "block" in matches.values(), (case["label"], matches)
        else:
            assert set(matches.values()) == {"advice"}, (case["label"], matches)


def test_no_silent_verdict_drift(replayed):
    expected = json.loads(EXPECTED.read_text())
    assert set(expected) == set(replayed)
    drift = {key: (expected[key], digest(value)) for key, value in replayed.items() if digest(value) != expected[key]}
    assert not drift, json.dumps(drift, indent=1)
