from __future__ import annotations

from openlabs import resources
from openlabs.config import FactorySettings


def test_effective_capacity_applies_aggregate_cpu_fraction(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(resources, "_cpu_threads", lambda: 20)
    monkeypatch.setattr(resources, "_memory_mib", lambda: (40_000, 40_000))

    capacity = resources.effective_capacity(
        tmp_path,
        FactorySettings(max_cpu_fraction_of_host=0.75, reserve_cpu_threads=2),
        {"cpu_threads": 0, "memory_mib": 0, "scratch_mib": 0},
    )

    assert capacity.cpu_threads == 15
