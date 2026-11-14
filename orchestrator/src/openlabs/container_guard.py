"""Verify kernel-enforced container limits, never trust an environment flag."""
from pathlib import Path
import os
import sys

GIB = 1024 ** 3


def validate(root: Path = Path('/sys/fs/cgroup')) -> None:
    quota, period = (root / 'cpu.max').read_text().split()
    ceiling = max(1, (os.cpu_count() or 1) * 75 // 100)
    if quota == 'max' or int(period) <= 0 or not 0 < int(quota) <= ceiling * int(period):
        raise ValueError('container CPU quota exceeds 75% of visible CPUs')
    for filename, limit in [('memory.max', 34 * GIB), ('memory.swap.max', 4 * GIB), ('pids.max', 2048)]:
        value = (root / filename).read_text().strip()
        if value == 'max' or not 0 <= int(value) <= limit:
            raise ValueError(f'container {filename} is missing or exceeds {limit}')
    # Host and container must flock the same inode, not two private lock dirs.
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    locks = runtime / 'openlabs-gpu-guard'
    mounts = [line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    if str(locks) not in mounts:
        raise ValueError('host-shared GPU lock directory is not mounted')
    info = locks.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('shared GPU lock directory must be private and owned by the caller')


if __name__ == '__main__':
    try:
        validate()
    except (OSError, ValueError) as exc:
        print(f'OpenLabs container guard: STOP: {exc}', file=sys.stderr)
        sys.exit(78)
    print('OpenLabs container guard: verified CPU/memory/swap/pids limits and shared GPU locks', file=sys.stderr)
