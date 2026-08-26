"""Small host-resource probe and reservation arithmetic for task admission."""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from math import floor
from pathlib import Path
from typing import Any

from .config import FactorySettings

MIB = 1024 * 1024
RESOURCE_KEYS = ("cpu_threads", "memory_mib", "scratch_mib")


@dataclass(frozen=True)
class ResourceVector:
    cpu_threads: int
    memory_mib: int
    scratch_mib: int

    def to_dict(self) -> dict[str, int]:
        return {key: int(getattr(self, key)) for key in RESOURCE_KEYS}

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
        *,
        allow_zero: bool = False,
    ) -> ResourceVector:
        source = value or {}
        parsed: dict[str, int] = {}
        minimum = 0 if allow_zero else 1
        for key in RESOURCE_KEYS:
            raw = source.get(key, 0)
            if not isinstance(raw, int) or isinstance(raw, bool) or raw < minimum:
                qualifier = "non-negative" if allow_zero else "positive"
                raise ValueError(f"resources.{key} must be a {qualifier} integer")
            parsed[key] = raw
        return cls(**parsed)


def default_task_resources(settings: FactorySettings) -> ResourceVector:
    return ResourceVector(
        settings.default_task_cpu_threads,
        settings.default_task_memory_mib,
        settings.default_task_scratch_mib,
    )


def task_resources(task: Mapping[str, Any]) -> ResourceVector:
    return ResourceVector.from_mapping(
        {
            "cpu_threads": task.get("cpu_threads"),
            "memory_mib": task.get("memory_mib"),
            "scratch_mib": task.get("scratch_mib"),
        }
    )


def _cpu_threads() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:  # pragma: no cover - non-Linux fallback.
        return max(1, int(os.cpu_count() or 1))


def _memory_mib() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(raw.strip().split()[0]) // 1024
    except (OSError, ValueError, IndexError):
        values = {}
    if "MemTotal" in values and "MemAvailable" in values:
        return values["MemTotal"], values["MemAvailable"]
    pages = int(os.sysconf("SC_PHYS_PAGES"))
    page_size = int(os.sysconf("SC_PAGE_SIZE"))
    total = max(1, pages * page_size // MIB)
    return total, total


def effective_capacity(
    workspace: Path,
    settings: FactorySettings,
    reserved: Mapping[str, Any],
) -> ResourceVector:
    """Return a conservative capacity for this tick.

    Static host totals prevent reservation overcommit. Current available RAM
    and disk add pressure protection without pretending that momentary free
    space replaces peak reservations.
    """

    used = ResourceVector.from_mapping(reserved, allow_zero=True)
    host_cpu = _cpu_threads()
    total_memory, available_memory = _memory_mib()
    disk = shutil.disk_usage(workspace)
    total_scratch = int(disk.total // MIB)
    available_scratch = int(disk.free // MIB)

    fraction_cpu = max(1, floor(host_cpu * settings.max_cpu_fraction_of_host))
    static_cpu = min(
        max(0, host_cpu - settings.reserve_cpu_threads),
        fraction_cpu,
    )
    static_memory = max(0, total_memory - settings.reserve_memory_mib)
    static_scratch = max(0, total_scratch - settings.reserve_scratch_mib)
    pressure_memory = used.memory_mib + max(0, available_memory - settings.reserve_memory_mib)
    pressure_scratch = used.scratch_mib + max(0, available_scratch - settings.reserve_scratch_mib)
    return ResourceVector(
        cpu_threads=static_cpu,
        memory_mib=min(static_memory, pressure_memory),
        scratch_mib=min(static_scratch, pressure_scratch),
    )
