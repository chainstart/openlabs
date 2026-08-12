"""Cross-process serialization for factory lifecycle mutations."""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager

from .config import WorkspacePaths


@contextmanager
def factory_operation_lock(paths: WorkspacePaths) -> Iterator[None]:
    """Serialize ticks, result promotion, and operator stop operations."""

    lock_path = paths.database / "live" / "factory-operation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
