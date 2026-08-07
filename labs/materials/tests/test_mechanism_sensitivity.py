from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from matfactory.mechanism_sensitivity import summarize_sensitivity  # noqa: E402


def _row(excess: float, p_value: float, *, quality: bool = True):
    return {
        "quality_gate_pass": quality,
        "primary_string": {
            "observed_minus_null_mean": excess,
            "empirical_upper_tail_p": p_value,
        },
        "reverse_pair_fraction_by_window_ps": {"1": 0.4, "2": 0.5},
    }


def test_sensitivity_requires_quality_and_stable_string_conclusion():
    stable = summarize_sensitivity([_row(0.1, 0.01), _row(0.05, 0.03)])
    assert stable["mechanism_robustness_gate_pass"] is True
    assert stable["cooperative_string_claim_supported_across_grid"] is True

    unstable = summarize_sensitivity([_row(0.1, 0.01), _row(-0.02, 0.4)])
    assert unstable["mechanism_robustness_gate_pass"] is False
    assert unstable["primary_string_excess_sign_stable"] is False

    failed_quality = summarize_sensitivity(
        [_row(0.1, 0.01), _row(0.1, 0.01, quality=False)]
    )
    assert failed_quality["all_settings_pass_quality"] is False
    assert failed_quality["mechanism_robustness_gate_pass"] is False
