from pathlib import Path

import pytest

from openlabs import container_guard as guard


@pytest.fixture
def limited_cgroup(tmp_path):
    for name, value in {
        'cpu.max': '100000 100000', 'memory.max': str(34 * guard.GIB),
        'memory.swap.max': str(4 * guard.GIB), 'pids.max': '512',
    }.items():
        (tmp_path / name).write_text(value)
    return tmp_path


@pytest.mark.parametrize('filename,value', [
    ('cpu.max', 'max 100000'), ('memory.max', 'max'),
    ('memory.max', str(35 * guard.GIB)), ('memory.swap.max', str(5 * guard.GIB)),
    ('pids.max', '513'),
])
def test_refuses_missing_or_excessive_limits(limited_cgroup, filename, value):
    (limited_cgroup / filename).write_text(value)
    with pytest.raises(ValueError):
        guard.validate(limited_cgroup)


def test_refuses_unshared_gpu_lock_directory(limited_cgroup, monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'private-runtime'))
    with pytest.raises(ValueError, match='not mounted'):
        guard.validate(limited_cgroup)
