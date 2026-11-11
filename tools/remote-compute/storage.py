"""Directory-based SSD pool. Never falls back to the system filesystem."""
from pathlib import Path
import json
import os
import shutil
import fcntl
import tempfile

CONFIG = Path('/etc/openlabs-remote/storage.json')


def volumes(config_path=None):
    config = json.loads(Path(config_path or CONFIG).read_text())
    entries = config.get('volumes', [])
    ids = [entry['id'] for entry in entries]
    if not entries or len(set(ids)) != len(ids):
        raise ValueError('empty or duplicate storage pool')
    return entries


def check(entry):
    mount = Path(entry['mount'])
    root = Path(entry['root'])
    if not mount.is_mount() or mount.stat().st_dev == Path('/').stat().st_dev:
        raise ValueError(f"{entry['id']}: experimental SSD is not mounted independently")
    if root.is_symlink() or root.resolve().parent != mount.resolve():
        raise ValueError(f"{entry['id']}: invalid worker storage root")
    if not root.is_dir() or root.stat().st_dev != mount.stat().st_dev:
        raise ValueError(f"{entry['id']}: worker directory is outside the mounted SSD")
    if not os.access(root, os.W_OK | os.X_OK):
        raise ValueError(f"{entry['id']}: worker cannot write to this SSD")
    return entry


def inventory(entries=None, checker=check, usage=shutil.disk_usage):
    result = []
    for entry in entries if entries is not None else volumes():
        item = dict(entry)
        try:
            checker(entry)
            space = usage(entry['root'])
            item.update(available=True, total_bytes=space.total, free_bytes=space.free)
        except (OSError, ValueError) as exc:
            item.update(available=False, error=str(exc))
        result.append(item)
    return result


def _remember(index_dir, job_id, entry):
    if index_dir is None:
        return
    fd, name = tempfile.mkstemp(prefix='.placement-', dir=index_dir)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump({'job_id': job_id, 'volume': entry['id'], 'root': entry['root']}, out)
        os.replace(name, Path(index_dir) / (job_id + '.json'))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def locate_job(job_id, requested='auto', entries=None, checker=check, usage=shutil.disk_usage,
               index_dir=None):
    if entries is None:
        config = json.loads(CONFIG.read_text())
        entries = volumes()
        index_dir = index_dir or config['placement_index']
    if index_dir is None:
        return _locate_job(job_id, requested, entries, checker, usage, None)
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (index_dir / 'placement.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _locate_job(job_id, requested, entries, checker, usage, index_dir)


def _locate_job(job_id, requested, entries, checker, usage, index_dir):
    """Retain existing placement; otherwise choose the mounted SSD with most free space."""
    entries = list(entries if entries is not None else volumes())
    if requested != 'auto' and requested not in {entry['id'] for entry in entries}:
        raise ValueError('unknown experimental SSD')
    index = Path(index_dir) / (job_id + '.json') if index_dir is not None else None
    if index is not None and index.exists():
        saved = json.loads(index.read_text())
        matches = [entry for entry in entries if entry['id'] == saved['volume']]
        if len(matches) != 1 or matches[0]['root'] != saved['root']:
            raise ValueError('recorded job storage is no longer configured')
        entry = matches[0]
        if requested != 'auto' and requested != entry['id']:
            raise ValueError('existing job placement differs from requested SSD')
        checker(entry)  # Offline: refuse, never re-run the same identity on another SSD.
        return Path(entry['root']) / 'jobs' / job_id, entry
    existing = []
    for entry in entries:
        path = Path(entry['root']) / 'jobs' / job_id
        if path.exists():
            checker(entry)
            if path.is_symlink() or not path.is_dir():
                raise ValueError('unsafe existing job directory')
            existing.append((path, entry))
    if len(existing) > 1:
        raise ValueError('job identity exists on more than one SSD')
    if existing:
        path, entry = existing[0]
        if requested != 'auto' and requested != entry['id']:
            raise ValueError('existing job placement differs from requested SSD')
        _remember(index_dir, job_id, entry)
        return path, entry
    candidates = []
    for entry in entries:
        if requested != 'auto' and entry['id'] != requested:
            continue
        try:
            checker(entry)
            candidates.append((usage(entry['root']).free, entry['id'], entry))
        except (OSError, ValueError):
            if requested != 'auto':
                raise
    if not candidates:
        raise ValueError('no mounted experimental SSD is available; system-disk fallback is forbidden')
    entry = max(candidates, key=lambda item: (item[0], item[1]))[2]
    _remember(index_dir, job_id, entry)
    return Path(entry['root']) / 'jobs' / job_id, entry


def entry_for_job(job, entries=None):
    root = Path(job).resolve().parent.parent
    for entry in entries if entries is not None else volumes():
        if Path(entry['root']).resolve() == root:
            check(entry)
            return entry
    raise ValueError('job does not belong to the configured experimental SSD pool')
