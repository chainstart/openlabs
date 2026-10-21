from __future__ import annotations

from pathlib import Path

from openlabs import resources
from openlabs.config import FactorySettings, load_settings, workspace_paths


def test_effective_capacity_applies_aggregate_cpu_fraction(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resources, "_cpu_threads", lambda: 20)
    monkeypatch.setattr(resources, "_memory_mib", lambda: (40_000, 40_000))

    capacity = resources.effective_capacity(
        tmp_path,
        FactorySettings(max_cpu_fraction_of_host=0.75, reserve_cpu_threads=2),
        {"cpu_threads": 0, "memory_mib": 0, "scratch_mib": 0},
    )

    assert capacity.cpu_threads == 15


def test_workstation_profile_admits_a_three_gib_pilot_on_an_eight_gib_host(
    tmp_path, monkeypatch,
) -> None:
    code_root = Path(__file__).resolve().parents[2]
    settings = load_settings(workspace_paths(code_root.parent))
    monkeypatch.setattr(resources, "_cpu_threads", lambda: 8)
    monkeypatch.setattr(resources, "_memory_mib", lambda: (7784, 6144))
    capacity = resources.effective_capacity(
        tmp_path, settings, {"cpu_threads": 0, "memory_mib": 0, "scratch_mib": 0},
    )
    assert capacity.cpu_threads >= 2
    assert 3072 <= capacity.memory_mib <= 6144 - 2048
    assert capacity.scratch_mib >= 2048
