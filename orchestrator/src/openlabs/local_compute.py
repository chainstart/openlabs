"""Local background compute queue: overflow for ailab, run in this container.

ailab is the preferred place for long CPU jobs and should be kept full; when it cannot
start a job now (its running plus queued declared CPUs would exceed its capacity) and
this container has room, ``bin/openlabs-remote submit`` (default ``--backend auto``)
puts the job here instead, so every agent gets the same routing whichever entry it
calls. ``bin/openlabs-local submit`` queues here explicitly. The layout mirrors the
remote queue so ``openlabs-remote status/wait`` and the orchestrator's yield-to-wait
mechanism (``openlabs.remote_wait``) cover both::

    jobs/JOB_ID/request.json   backend "local", argv, resources, created_at, routing?
    jobs/JOB_ID/status.json    {job_id, state, updated_at, pid?, exit_code?, error?}
    jobs/JOB_ID/source/        snapshot of the submitted source directory
    jobs/JOB_ID/result/        stdout.log, stderr.log, receipt.json, outputs/
    jobs/JOB_ID/READY          written last; presence = dispatchable

Jobs never start at submission: a submitting agent's process tree (and the resource
guard ``bin/openlabs-remote`` runs in) is torn down when it exits, and that used to kill
the runner (2026-11-14, job 946ac0f9). ``dispatch`` runs in each orchestrator tick
(or ``bin/openlabs-local dispatch`` from a long-lived shell) and starts queued jobs
while the local limits allow: ``max_jobs`` jobs, ``max_cpus`` declared CPUs and
``max_memory_mib`` declared memory at once (``config/local-compute.json``; the
environment variables ``OPENLABS_LOCAL_MAX_JOBS``/``_MAX_CPUS``/``_MAX_MEMORY_MIB``
override it). Each job runs detached inside ``bin/openlabs-resource-guard --task-type
cpu`` with no GPU visible, and records its own end and a receipt.

Automatic overflow only takes a job that can run here unchanged: CPU task type (math
keeps its own rules), default storage, and a source whose scripts neither install nor
download anything nor use a path this container lacks. Registered environment aliases
(e.g. the ailab astronomy venv -> the container venv built from the same hash lock) are
rewritten in the snapshot and recorded in ``request.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .remote_compute import (
    JOB_ID_RE,
    RemoteComputeError,
    SourceScan,
    _write_private_atomic,
    safe_arcname,
    scan_source,
    validate_argv,
    validate_resources,
)

DEFAULT_MAX_JOBS = 3
DEFAULT_MAX_CPUS = 8
DEFAULT_MAX_MEMORY_MIB = 16384
DEFAULT_MIN_FREE_MEMORY_MIB = 8192
STARTUP_GRACE_SECONDS = 120
TERMINAL_STATES = ('succeeded', 'failed')
CODE_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = CODE_ROOT / 'config' / 'local-compute.json'
REMOTE_CONFIG_PATH = CODE_ROOT / 'config' / 'remote-compute.json'
CGROUP_ROOT = Path('/sys/fs/cgroup')
MOVED_MARKER = 'WITHDRAWN.moved-to-local'
MIB = 1024 * 1024

# Files whose text is checked for portability and alias rewriting.
SCRIPT_SUFFIXES = frozenset({'', '.sh', '.bash', '.zsh', '.py', '.source', '.r', '.jl', '.pl'})
MAX_SCRIPT_BYTES = 1024 * 1024
NONPORTABLE_PATTERNS = (
    (re.compile(r'\bdownload-direct\b'), 'uses the ailab download helper'),
    (re.compile(r'\b(?:uv\s+pip|pip3?|python3?\s+-m\s+pip)\s+install\b'), 'installs packages'),
    (re.compile(r'\buv\s+(?:venv|sync|add|tool\s+install|python\s+install)\b'),
     'builds an environment'),
    (re.compile(r'\b(?:conda|mamba|micromamba)\s+(?:install|create|env)\b'),
     'builds an environment'),
    (re.compile(r'\bapt(?:-get)?\s+install\b'), 'installs system packages'),
    (re.compile(r'\b(?:curl|wget|aria2c)\b'), 'downloads'),
    (re.compile(r'\bgit\s+(?:clone|fetch|pull)\b'), 'downloads'),
    (re.compile(r'\burllib\.request\b|\brequests\.(?:get|post)\b|\bhttpx\b'), 'uses the network'),
    (re.compile(r'\bOPENLABS_STORAGE_ROOTS?\b'), 'uses ailab SSD storage'),
    (re.compile(r'\b(?:podman|docker)\b'), 'uses containers'),
)
ABSOLUTE_PATH = re.compile(
    r'(?<![\w.$}/~-])(/(?:data|usr|opt|srv|home|mnt|scratch|workspace|bin|sbin|lib|lib64)'
    r'(?:/[^\s\'"`;|&<>(){}\[\],:=$*?]*)?)'
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_queue_root(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get('OPENLABS_LOCAL_QUEUE', '').strip()
    if configured:
        return Path(configured).expanduser()
    return Path('/workspace/.openlabs-local-compute')


def _json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_settings(environ: Mapping[str, str] | None = None,
                  config_path: Path | None = None) -> dict[str, Any]:
    """Local limits and overflow switches: environment > config file > defaults."""

    env = os.environ if environ is None else environ
    config = _json(config_path or CONFIG_PATH) or {}

    def number(env_name: str, key: str, default: int) -> int:
        for raw in (env.get(env_name, ''), config.get(key)):
            try:
                if raw not in ('', None) and not isinstance(raw, bool):
                    return max(1, int(raw))
            except (TypeError, ValueError):
                continue
        return default

    switch = str(env.get('OPENLABS_COMPUTE_OVERFLOW', '')).strip().lower()
    auto = config.get('auto_overflow', True) is not False
    if switch in ('0', 'false', 'no', 'off'):
        auto = False
    elif switch in ('1', 'true', 'yes', 'on'):
        auto = True
    aliases = config.get('environment_aliases') or {}
    return {
        'auto_overflow': auto,
        'max_jobs': number('OPENLABS_LOCAL_MAX_JOBS', 'max_jobs', DEFAULT_MAX_JOBS),
        'max_cpus': number('OPENLABS_LOCAL_MAX_CPUS', 'max_cpus', DEFAULT_MAX_CPUS),
        'max_memory_mib': number('OPENLABS_LOCAL_MAX_MEMORY_MIB', 'max_memory_mib',
                                 DEFAULT_MAX_MEMORY_MIB),
        'min_free_memory_mib': number('OPENLABS_LOCAL_MIN_FREE_MEMORY_MIB',
                                      'min_free_memory_mib', DEFAULT_MIN_FREE_MEMORY_MIB),
        'environment_aliases': {
            str(key).rstrip('/'): str(value).rstrip('/')
            for key, value in (aliases.items() if isinstance(aliases, Mapping) else ())
            if str(key).startswith('/') and str(value).startswith('/')
        },
    }


def limits(environ: Mapping[str, str] | None = None) -> tuple[int, int]:
    current = load_settings(environ)
    return current['max_jobs'], current['max_cpus']


def _write_status(directory: Path, **fields: Any) -> dict[str, Any]:
    status = {**(_json(directory / 'status.json') or {}), **fields,
              'job_id': directory.name, 'updated_at': utc_now()}
    _write_private_atomic(directory / 'status.json',
                          (json.dumps(status, indent=2, sort_keys=True) + '\n').encode())
    return status


# ------------------------------------------------------------------ portability

def _script_files(root: Path, argv: Sequence[str]) -> list[Path]:
    named = {Path(item).name for item in argv}
    found = []
    for path in sorted(root.rglob('*')):
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SCRIPT_BYTES:
            continue
        if path.suffix.lower() not in SCRIPT_SUFFIXES and path.name not in named:
            continue
        try:
            head = path.read_bytes()[:8192]
        except OSError:
            continue
        if b'\x00' in head:
            continue
        found.append(path)
    return found


def _replace_aliases(text: str, aliases: Mapping[str, str]) -> str:
    for source in sorted(aliases, key=len, reverse=True):
        text = re.sub(re.escape(source) + r'(?=$|[/\s\'"`;:)}\]])', aliases[source], text)
    return text


def usable_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    """Only aliases whose container side exists can be applied."""

    return {key: value for key, value in aliases.items() if Path(value).exists()}


def apply_aliases(root: Path, argv: Sequence[str],
                  aliases: Mapping[str, str]) -> tuple[list[str], list[dict[str, str]]]:
    """Rewrite registered ailab paths in the snapshot's scripts and in argv."""

    aliases = usable_aliases(aliases)
    rewrites: list[dict[str, str]] = []
    if not aliases:
        return list(argv), rewrites
    for path in _script_files(root, argv):
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        new = _replace_aliases(text, aliases)
        if new != text:
            data = new.encode('utf-8')
            mode = stat.S_IMODE(path.stat().st_mode)
            path.write_bytes(data)
            os.chmod(path, mode)
            rewrites.append({'file': path.relative_to(root).as_posix(),
                             'sha256_before': hashlib.sha256(raw).hexdigest(),
                             'sha256_after': hashlib.sha256(data).hexdigest()})
    new_argv = [_replace_aliases(item, aliases) for item in argv]
    if new_argv != list(argv):
        rewrites.append({'file': '<argv>', 'before': json.dumps(list(argv)),
                         'after': json.dumps(new_argv)})
    return new_argv, rewrites


def _path_available(text: str) -> bool:
    candidate = Path(text.rstrip('.'))
    if candidate.exists():
        return True
    # A file a script may create under an existing shared workspace directory is fine;
    # a missing executable, library or ailab disk path is not.
    return str(candidate).startswith('/workspace/') and candidate.parent.is_dir() and str(
        candidate.parent) != '/workspace'


def portability_problems(texts: Mapping[str, str], argv: Sequence[str],
                         aliases: Mapping[str, str] | None = None) -> list[str]:
    """Reasons a job written for ailab would not run here unchanged (empty = portable).

    ``texts`` maps a relative file name to its script text; aliases are applied first.
    """

    aliases = usable_aliases(aliases or {})
    problems: list[str] = []
    items = dict(texts)
    items['<argv>'] = ' '.join(argv)
    for name, text in items.items():
        text = _replace_aliases(text, aliases)
        for pattern, why in NONPORTABLE_PATTERNS:
            match = pattern.search(text)
            if match:
                problems.append(f'{name}: {why} ({match.group(0)!r})')
        for match in ABSOLUTE_PATH.finditer(text):
            path = match.group(1)
            if not _path_available(path):
                problems.append(f'{name}: needs {path}, absent in this container')
        if len(problems) >= 8:
            break
    return sorted(set(problems))


def scan_texts(scan: SourceScan, argv: Sequence[str]) -> dict[str, str]:
    named = {Path(item).name for item in argv}
    texts: dict[str, str] = {}
    for entry in scan.entries:
        if entry.is_dir or entry.size > MAX_SCRIPT_BYTES:
            continue
        path = Path(entry.arcname)
        if path.suffix.lower() not in SCRIPT_SUFFIXES and path.name not in named:
            continue
        try:
            raw = entry.path.read_bytes()
        except OSError:
            continue
        if b'\x00' in raw[:8192]:
            continue
        texts[entry.arcname] = raw.decode('utf-8', errors='replace')
    return texts


def directory_texts(root: Path, argv: Sequence[str]) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): path.read_text(encoding='utf-8', errors='replace')
            for path in _script_files(root, argv)}


# ---------------------------------------------------------------------- load

def _jobs(root: Path) -> list[tuple[Path, dict[str, Any], dict[str, Any]]]:
    rows = []
    try:
        directories = sorted(path for path in (root / 'jobs').iterdir() if path.is_dir())
    except OSError:
        return rows
    for directory in directories:
        if not JOB_ID_RE.match(directory.name) or not (directory / 'READY').is_file():
            continue
        request, status = _json(directory / 'request.json'), _json(directory / 'status.json')
        if request is None or status is None:
            continue
        rows.append((directory, request, status))
    rows.sort(key=lambda row: str(row[1].get('created_at') or ''))
    return rows


def _resources(request: Mapping[str, Any]) -> tuple[int, int]:
    resources = request.get('resources') or {}
    try:
        return int(resources.get('cpu_threads') or 0), int(resources.get('memory_mib') or 0)
    except (TypeError, ValueError):
        return 0, 0


def local_load(queue_root: Path | None = None) -> dict[str, Any]:
    """Declared load of the local queue (running and queued, READY jobs only)."""

    root = Path(queue_root) if queue_root is not None else default_queue_root()
    load = {'running': 0, 'queued': 0, 'running_cpus': 0, 'running_memory_mib': 0,
            'queued_cpus': 0, 'queued_memory_mib': 0}
    for _, request, status in _jobs(root):
        state = status.get('state')
        if state not in ('running', 'queued'):
            continue
        cpus, memory = _resources(request)
        load[state] += 1
        load[f'{state}_cpus'] += cpus
        load[f'{state}_memory_mib'] += memory
    return load


def summary(queue_root: Path | None = None,
            environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Tick-report view: local load against the configured limits."""

    current = load_settings(environ)
    return {**local_load(queue_root),
            **{key: current[key] for key in ('auto_overflow', 'max_jobs', 'max_cpus',
                                             'max_memory_mib')}}


def ailab_load(remote_root: Path, capabilities: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Declared ailab load as the bridge sees it (withdrawn / non-READY queued ignored)."""

    load = {'running': 0, 'queued': 0, 'running_cpus': 0, 'running_memory_mib': 0,
            'queued_cpus': 0, 'queued_memory_mib': 0}
    try:
        directories = [item for item in (Path(remote_root) / 'jobs').iterdir() if item.is_dir()]
    except OSError:
        directories = []
    for directory in directories:
        status = _json(directory / 'status.json') or {}
        state = status.get('state')
        if state not in ('running', 'queued'):
            continue
        try:
            if any(directory.glob('WITHDRAWN*')):
                continue
        except OSError:
            continue
        if state == 'queued' and not (directory / 'READY').is_file():
            continue
        cpus, memory = _resources(_json(directory / 'request.json') or {})
        load[state] += 1
        load[f'{state}_cpus'] += cpus
        load[f'{state}_memory_mib'] += memory
    caps = capabilities or {}
    for key in ('cpu_threads', 'memory_mib', 'max_concurrent_jobs'):
        value = caps.get(key)
        load[f'capacity_{key}'] = value if isinstance(value, int) and value > 0 else None
    return load


def _container_free_memory_mib(root: Path = CGROUP_ROOT) -> int | None:
    try:
        limit = (root / 'memory.max').read_text().strip()
        current = int((root / 'memory.current').read_text().strip())
        stats = dict(line.split(' ', 1) for line in
                     (root / 'memory.stat').read_text().splitlines() if ' ' in line)
    except (OSError, ValueError):
        return None
    if not limit.isdigit():
        return None
    used = current - int(stats.get('file', '0').strip() or 0)
    return (int(limit) - max(0, used)) // MIB


def overflow_decision(
    *,
    cpu_threads: int,
    memory_mib: int,
    task_type: str,
    storage: str,
    texts: Mapping[str, str],
    argv: Sequence[str],
    remote_root: Path,
    local_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    capabilities: Mapping[str, Any] | None = None,
    free_memory_mib: int | None | str = 'measure',
) -> dict[str, Any]:
    """Where an ``auto`` job goes: ``ailab`` unless ailab is full and this container
    can start the job now and run it unchanged."""

    current = load_settings(environ)
    decision: dict[str, Any] = {'backend': 'ailab', 'decided_at': utc_now()}

    def keep(reason: str) -> dict[str, Any]:
        return {**decision, 'reason': reason}

    if not current['auto_overflow']:
        return keep('automatic overflow is switched off')
    if task_type != 'cpu':
        return keep(f'task type {task_type} keeps its own rules')
    if storage != 'auto':
        return keep(f'explicit ailab storage {storage}')
    if capabilities is None:
        capabilities = _json(REMOTE_CONFIG_PATH) or {}
    if not capabilities.get('enabled'):
        return keep('ailab capabilities not configured')
    ailab = ailab_load(remote_root, capabilities)
    decision['ailab'] = ailab
    cap_cpu, cap_mem = ailab['capacity_cpu_threads'], ailab['capacity_memory_mib']
    cap_jobs = ailab['capacity_max_concurrent_jobs']
    committed_cpu = ailab['running_cpus'] + ailab['queued_cpus']
    committed_mem = ailab['running_memory_mib'] + ailab['queued_memory_mib']
    committed_jobs = ailab['running'] + ailab['queued']
    full = (
        (cap_cpu is not None and committed_cpu + cpu_threads > cap_cpu)
        or (cap_mem is not None and committed_mem + memory_mib > cap_mem)
        or (cap_jobs is not None and committed_jobs + 1 > cap_jobs)
    )
    if not full:
        return keep('ailab can start it now')
    local = local_load(local_root)
    decision['local'] = local
    committed_local_jobs = local['running'] + local['queued']
    if committed_local_jobs + 1 > current['max_jobs']:
        return keep(f'local queue full ({committed_local_jobs} of {current["max_jobs"]} jobs)')
    if local['running_cpus'] + local['queued_cpus'] + cpu_threads > current['max_cpus']:
        return keep(f'local CPUs full (limit {current["max_cpus"]})')
    if (local['running_memory_mib'] + local['queued_memory_mib'] + memory_mib
            > current['max_memory_mib']):
        return keep(f'local memory full (limit {current["max_memory_mib"]} MiB)')
    free = _container_free_memory_mib() if free_memory_mib == 'measure' else free_memory_mib
    if isinstance(free, int):
        decision['container_free_memory_mib'] = free
        if free - local['queued_memory_mib'] - memory_mib < current['min_free_memory_mib']:
            return keep('container memory headroom too small')
    problems = portability_problems(texts, argv, current['environment_aliases'])
    if problems:
        decision['not_portable'] = problems
        return keep('job is not portable to this container')
    return {**decision, 'backend': 'local',
            'reason': 'ailab full; container has room and the job runs here unchanged'}


# -------------------------------------------------------------------- submit

def _copy_scan(scan: SourceScan, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    for entry in scan.entries:
        target = destination / safe_arcname(entry.arcname)
        if entry.is_dir:
            target.mkdir(exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        with os.fdopen(os.open(entry.path, flags), 'rb') as handle, open(target, 'wb') as out:
            shutil.copyfileobj(handle, out)
        os.chmod(target, entry.mode & 0o777)


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_file() and not path.is_symlink():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b'\n')
    return digest.hexdigest()


def _publish(directory: Path, request: dict[str, Any], *, ready: bool = True) -> None:
    _write_private_atomic(directory / 'request.json',
                          (json.dumps(request, indent=2, sort_keys=True) + '\n').encode())
    _write_status(directory, state='queued')
    if ready:
        _write_private_atomic(directory / 'READY', (directory.name + '\n').encode())


def submit(source: Path, argv: Sequence[str], *, cpu_threads: int, memory_mib: int,
           wall_seconds: int, queue_root: Path | None = None,
           scan: SourceScan | None = None, routing: Mapping[str, Any] | None = None,
           environ: Mapping[str, str] | None = None) -> str:
    """Snapshot ``source`` into the local queue (not started; see ``dispatch``)."""

    argv = validate_argv(list(argv))
    resources = validate_resources(cpu_threads, memory_mib, wall_seconds)
    source = Path(source).resolve()
    if not source.is_dir():
        raise RemoteComputeError(f'source is not a directory: {source}')
    scan = scan if scan is not None else scan_source(source)
    root = Path(queue_root) if queue_root is not None else default_queue_root()
    job_id = uuid.uuid4().hex
    directory = root / 'jobs' / job_id
    directory.mkdir(parents=True, mode=0o700)
    _copy_scan(scan, directory / 'source')
    argv, rewrites = apply_aliases(directory / 'source', argv,
                                   load_settings(environ)['environment_aliases'])
    request: dict[str, Any] = {
        'schema_version': 'openlabs.local-compute.v1', 'job_id': job_id,
        'backend': 'local', 'argv': argv, 'resources': resources,
        'source': str(source), 'source_sha256': _source_digest(directory / 'source'),
        'created_at': utc_now()}
    if rewrites:
        request['path_rewrites'] = rewrites
    if routing:
        request['routing'] = dict(routing)
    _publish(directory, request)
    return job_id


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(mode=0o700)
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar.getmembers():
            name = safe_arcname(member.name.rstrip('/'))
            target = destination / name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                raise RemoteComputeError(f'payload entry is not a plain file: {name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(member)
            if handle is None:
                raise RemoteComputeError(f'unreadable payload entry: {name}')
            with handle, open(target, 'wb') as out:
                shutil.copyfileobj(handle, out)
            os.chmod(target, member.mode & 0o777)


def adopt_remote(job_id: str, *, remote_root: Path, queue_root: Path | None = None,
                 environ: Mapping[str, str] | None = None, reason: str = '') -> dict[str, Any]:
    """Move a still-queued ailab job here under the same job id (lossless or not at all).

    The ailab copy is withdrawn (READY -> READY.withdrawn plus ``WITHDRAWN.moved-to-local``),
    so the bridge never starts it; ``openlabs-remote status/wait`` and ``remote_wait``
    follow the marker to this queue, so waits on the id keep working.
    """

    if not JOB_ID_RE.match(job_id):
        raise RemoteComputeError('job id must be 32 lowercase hex characters')
    remote = Path(remote_root) / 'jobs' / job_id
    request = _json(remote / 'request.json')
    status = _json(remote / 'status.json')
    if request is None or status is None:
        raise RemoteComputeError(f'no ailab job {job_id}')
    if status.get('state') != 'queued' or not (remote / 'READY').is_file():
        raise RemoteComputeError(f'ailab job {job_id} is not queued and dispatchable')
    if any(remote.glob('WITHDRAWN*')) or (remote / 'transport.log').exists():
        raise RemoteComputeError(f'ailab job {job_id} is withdrawn or already in transfer')
    if request.get('task_type', 'cpu') != 'cpu' or request.get('storage'):
        raise RemoteComputeError(f'ailab job {job_id} uses math rules or pinned ailab storage')
    payload = remote / 'payload.tar.gz'
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    if digest != request.get('payload_sha256'):
        raise RemoteComputeError(f'payload hash mismatch for {job_id}')
    resources = validate_resources(**{key: (request.get('resources') or {}).get(key)
                                      for key in ('cpu_threads', 'memory_mib', 'wall_seconds')})
    root = Path(queue_root) if queue_root is not None else default_queue_root()
    directory = root / 'jobs' / job_id
    if directory.exists():
        raise RemoteComputeError(f'local job {job_id} already exists')
    current = load_settings(environ)
    directory.mkdir(parents=True, mode=0o700)
    try:
        _safe_extract(payload, directory / 'source')
        argv = validate_argv(request.get('argv'))
        problems = portability_problems(directory_texts(directory / 'source', argv), argv,
                                        current['environment_aliases'])
        if problems:
            raise RemoteComputeError('not portable to this container: ' + '; '.join(problems))
        argv, rewrites = apply_aliases(directory / 'source', argv, current['environment_aliases'])
        local_request: dict[str, Any] = {
            'schema_version': 'openlabs.local-compute.v1', 'job_id': job_id,
            'backend': 'local', 'argv': argv, 'resources': resources,
            'source': f'ailab payload {remote / "payload.tar.gz"}',
            'payload_sha256': digest,
            'source_sha256': _source_digest(directory / 'source'),
            'created_at': utc_now(),
            'moved_from': {'backend': 'ailab', 'job_dir': str(remote),
                           'created_at': request.get('created_at'), 'reason': reason}}
        if rewrites:
            local_request['path_rewrites'] = rewrites
        _publish(directory, local_request, ready=False)
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    # Withdraw on ailab, then re-check that the bridge had not taken it meanwhile.
    os.replace(remote / 'READY', remote / 'READY.withdrawn')
    marker = remote / MOVED_MARKER
    marker.write_text(json.dumps({'moved_to': 'local', 'local_job_dir': str(directory),
                                  'at': utc_now(), 'reason': reason}, sort_keys=True) + '\n')
    after = _json(remote / 'status.json') or {}
    if after.get('state') != 'queued' or (remote / 'transport.log').exists():
        marker.unlink(missing_ok=True)
        os.replace(remote / 'READY.withdrawn', remote / 'READY')
        shutil.rmtree(directory, ignore_errors=True)
        raise RemoteComputeError(f'ailab took job {job_id} while moving it; left on ailab')
    _write_private_atomic(directory / 'READY', (job_id + '\n').encode())
    return {'job_id': job_id, 'local_job_dir': str(directory), 'rewrites': rewrites}


def locate(job_id: str, remote_root: Path, local_root: Path | None = None) -> tuple[str, Path]:
    """(backend, job directory) for an id from either queue; a moved ailab job resolves
    to its local copy."""

    remote = Path(remote_root) / 'jobs' / job_id
    local = (Path(local_root) if local_root is not None else default_queue_root()) / 'jobs' / job_id
    if remote.is_dir() and not ((remote / MOVED_MARKER).exists() and local.is_dir()):
        return 'ailab', remote
    if local.is_dir():
        return 'local', local
    return 'ailab', remote


# ------------------------------------------------------------------ dispatch

def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def dispatch(queue_root: Path | None = None, *, max_jobs: int | None = None,
             max_cpus: int | None = None, max_memory_mib: int | None = None,
             launch: bool = True) -> dict[str, Any]:
    """Reap dead runners and start queued jobs within the local limits.

    Call it from a long-lived process (the orchestrator tick): the runner is a detached
    child and must outlive the caller's process tree.
    """

    root = Path(queue_root) if queue_root is not None else default_queue_root()
    current = load_settings()
    max_jobs = max_jobs or current['max_jobs']
    max_cpus = max_cpus or current['max_cpus']
    max_memory_mib = max_memory_mib or current['max_memory_mib']
    summary_: dict[str, Any] = {'started': [], 'reaped': [], 'running': 0, 'queued': 0}
    running_cpus = running_memory = running = 0
    queued: list[tuple[Path, dict[str, Any]]] = []
    for directory, request, status in _jobs(root):
        state = status.get('state')
        if state == 'running':
            dispatched = str(status.get('dispatched_at') or '')
            starting = status.get('runner_pid') is None and dispatched and (
                datetime.now(timezone.utc) - datetime.fromisoformat(dispatched)
            ).total_seconds() < STARTUP_GRACE_SECONDS
            if not starting and not _alive(status.get('runner_pid')):
                _write_status(directory, state='failed', error='local runner exited without '
                              'recording a result (container or loop restart?)')
                summary_['reaped'].append(directory.name)
                continue
            cpus, memory = _resources(request)
            running += 1
            running_cpus += cpus
            running_memory += memory
        elif state == 'queued':
            queued.append((directory, request))
    for directory, request in queued:
        cpus, memory = _resources(request)
        if (not launch or running >= max_jobs or running_cpus + cpus > max_cpus
                or running_memory + memory > max_memory_mib):
            continue
        # Mark it before spawning: the runner records its own pid and its end, so a fast
        # job's terminal state is never overwritten by this process.
        _write_status(directory, state='running', runner_pid=None, dispatched_at=utc_now())
        log = open(directory / 'runner.log', 'ab')  # noqa: SIM115 - handed to the child
        subprocess.Popen(
            [sys.executable, '-m', 'openlabs.local_compute', 'run', directory.name,
             '--queue-root', str(root)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True,
            env={**os.environ, 'PYTHONPATH': str(CODE_ROOT / 'orchestrator' / 'src')},
        )
        log.close()
        running += 1
        running_cpus += cpus
        running_memory += memory
        summary_['started'].append(directory.name)
    summary_['running'] = running
    summary_['queued'] = sum(1 for _, _, status in _jobs(root) if status.get('state') == 'queued')
    return summary_


class _Interrupted(Exception):
    pass


def _receipt(directory: Path, request: Mapping[str, Any], code: int,
             error: str | None) -> str:
    outputs = directory / 'result' / 'outputs'
    files = []
    for path in sorted(outputs.rglob('*'))[:5000]:
        if path.is_file() and not path.is_symlink():
            files.append({'path': path.relative_to(outputs).as_posix(),
                          'bytes': path.stat().st_size,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    request_bytes = (directory / 'request.json').read_bytes()
    receipt = {'schema_version': 'openlabs.local-compute.receipt.v1',
               'job_id': directory.name, 'backend': 'local',
               'request_sha256': hashlib.sha256(request_bytes).hexdigest(),
               'source_sha256': request.get('source_sha256'),
               'payload_sha256': request.get('payload_sha256'),
               'path_rewrites': request.get('path_rewrites') or [],
               'exit_code': code, 'error': error, 'finished_at': utc_now(),
               'outputs': files}
    data = (json.dumps(receipt, indent=2, sort_keys=True) + '\n').encode()
    _write_private_atomic(directory / 'result' / 'receipt.json', data)
    return hashlib.sha256(data).hexdigest()


def run(job_id: str, queue_root: Path | None = None) -> int:
    """Execute one job inside the resource guard and record its end (runs detached)."""

    root = Path(queue_root) if queue_root is not None else default_queue_root()
    directory = root / 'jobs' / job_id
    request = _json(directory / 'request.json') or {}
    resources = request.get('resources') or {}
    result = directory / 'result'
    (result / 'outputs').mkdir(parents=True, exist_ok=True)
    scratch = directory / 'scratch'
    scratch.mkdir(exist_ok=True)
    threads = str(resources.get('cpu_threads') or 1)
    env = {**os.environ, 'OPENLABS_OUTPUT_DIR': str(result / 'outputs'),
           'OPENLABS_SCRATCH_DIR': str(scratch), 'TMPDIR': str(scratch),
           'OMP_NUM_THREADS': os.environ.get('OMP_NUM_THREADS', '1'),
           'OPENLABS_JOB_CPUS': threads, 'OPENLABS_JOB_ID': job_id,
           'OPENLABS_COMPUTE_BACKEND': 'local',
           # CPU jobs only: GPU work reserves the device through the guard explicitly.
           'CUDA_VISIBLE_DEVICES': ''}
    command = [str(CODE_ROOT / 'bin' / 'openlabs-resource-guard'), '--task-type', 'cpu', '--',
               *request.get('argv', [])]
    _write_status(directory, state='running', runner_pid=os.getpid(), started_at=utc_now())

    def interrupted(signum: int, _frame: Any) -> None:
        raise _Interrupted(f'interrupted by signal {signum} (loop or container stop?)')

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, interrupted)
    process: subprocess.Popen[bytes] | None = None
    with open(result / 'stdout.log', 'wb') as out, open(result / 'stderr.log', 'wb') as err:
        try:
            process = subprocess.Popen(command, cwd=directory / 'source', env=env,
                                       stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            code = process.wait(timeout=int(resources.get('wall_seconds') or 1))
            error = None
        except subprocess.TimeoutExpired:
            code, error = 124, f"timed out after {resources.get('wall_seconds')} s"
        except _Interrupted as exc:
            code, error = 130, str(exc)
        except OSError as exc:
            code, error = 127, str(exc)
        for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(signum, signal.SIG_IGN)
        if process is not None and process.poll() is None:
            # The guard forwards SIGTERM to its command and cleans up its descendants.
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    state = 'succeeded' if code == 0 else 'failed'
    try:
        receipt = _receipt(directory, request, code, error)
    except OSError:
        receipt = None
    _write_status(directory, state=state, exit_code=code, finished_at=utc_now(),
                  **({'receipt_sha256': receipt} if receipt else {}),
                  **({'error': error or f'exit code {code}'} if code else {}))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if args_list and args_list[0] == 'submit':
        if '--' not in args_list:
            print('openlabs-local submit: the command must follow "--"', file=sys.stderr)
            return 2
        split = args_list.index('--')
        args_list, command = args_list[:split], args_list[split + 1:]
    parser = argparse.ArgumentParser(prog='openlabs-local')
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('submit')
    s.add_argument('--source', required=True)
    s.add_argument('--cpus', required=True, type=int)
    s.add_argument('--memory-mib', required=True, type=int)
    s.add_argument('--timeout-seconds', required=True, type=int)
    st = sub.add_parser('status')
    st.add_argument('job_id')
    sub.add_parser('dispatch')
    sub.add_parser('summary')
    a = sub.add_parser('adopt-ailab')
    a.add_argument('job_id')
    a.add_argument('--reason', default='')
    r = sub.add_parser('run')
    r.add_argument('job_id')
    r.add_argument('--queue-root')
    args = parser.parse_args(args_list)
    try:
        if args.action == 'submit':
            job_id = submit(Path(args.source), command, cpu_threads=args.cpus,
                            memory_mib=args.memory_mib, wall_seconds=args.timeout_seconds)
            directory = default_queue_root() / 'jobs' / job_id
            problems = portability_problems(
                directory_texts(directory / 'source', command), command)
            for problem in problems:
                print(f'warning: {problem}', file=sys.stderr)
            print(f'job_id: {job_id}')
            print(f'job_dir: {directory}')
            print('backend: local')
            print('starts at the next orchestrator tick (bin/openlabs-local dispatch)')
            return 0
        if args.action == 'status':
            status = _json(default_queue_root() / 'jobs' / args.job_id / 'status.json')
            if status is None:
                print(f'no status for local job {args.job_id}', file=sys.stderr)
                return 3
            print(json.dumps(status, indent=2, sort_keys=True))
            return 0
        if args.action == 'dispatch':
            print(json.dumps(dispatch(), indent=2, sort_keys=True))
            return 0
        if args.action == 'summary':
            print(json.dumps(summary(), indent=2, sort_keys=True))
            return 0
        if args.action == 'adopt-ailab':
            from .remote_compute import default_queue_root as remote_queue_root

            moved = adopt_remote(args.job_id, remote_root=remote_queue_root(),
                                 reason=args.reason)
            print(json.dumps(moved, indent=2, sort_keys=True))
            return 0
        if args.action == 'run':
            return run(args.job_id, Path(args.queue_root) if args.queue_root else None)
    except RemoteComputeError as exc:
        print(f'openlabs-local: {exc}', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
