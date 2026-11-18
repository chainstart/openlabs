"""Client side of the OpenLabs remote compute file queue (openlabs.remote-compute.v1).

A container session submits a CPU job by writing a self-contained job directory
into a shared queue; a WSL bridge dispatches it to the ailab gateway and writes
results back.  The client needs no network route, no SSH key and no database.

Queue layout (root: $OPENLABS_REMOTE_QUEUE, else /workspace/.openlabs-remote in
the container, else ~/work/projects/.openlabs-remote on WSL)::

    jobs/JOB_ID/payload.tar.gz   source directory archive (entries relative to it)
    jobs/JOB_ID/request.json     schema_version, job_id, backend, argv, resources,
                                 payload_sha256, payload_bytes, created_at
    jobs/JOB_ID/status.json      {job_id, state, updated_at, receipt_sha256?, error?}
    jobs/JOB_ID/READY            written last and atomically; presence = dispatchable
    jobs/JOB_ID/result/          receipt.json, stdout.log, stderr.log, outputs/ (bridge)

Run it through the resource guard, e.g. ``bin/openlabs-remote`` (which wraps
``bin/openlabs-resource-guard --task-type cpu --``).  If you invoke
``python3 -m openlabs.remote_compute`` directly, wrap it in that guard yourself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence

SCHEMA_VERSION = 'openlabs.remote-compute.v1'
BACKENDS = ('ailab',)
# CLI choices: `auto` (default) keeps ailab first and overflows to the local container
# queue (openlabs.local_compute) when ailab is full; `local` queues there explicitly.
CLI_BACKENDS = ('auto', 'ailab', 'local')
STORAGE_CHOICES = ('auto', 'ssd1', 'ssd2', 'ssd3', 'ssd4', 'ssd5', 'ssd6')
STATES = ('queued', 'running', 'succeeded', 'failed')
TERMINAL_STATES = ('succeeded', 'failed')

CPU_RANGE = (1, 8)
MEMORY_MIB_RANGE = (128, 62961)
WALL_SECONDS_RANGE = (1, 31536000)
MAX_PAYLOAD_SOURCE_BYTES = 1024 ** 3
MAX_PAYLOAD_FILES = 10000
POLL_SECONDS = 2.0

CONTAINER_QUEUE = Path('/workspace/.openlabs-remote')
WSL_QUEUE_RELATIVE = Path('work/projects/.openlabs-remote')

EXCLUDED_DIR_NAMES = frozenset({
    '.git', '.venv', 'venv', '__pycache__', 'node_modules', 'secret-key',
    '.ssh', '.claude', '.codex', '.gnupg', '.aws', '.azure', '.kube', '.docker',
})
EXCLUDED_FILE_NAMES = frozenset({
    '.env', '.netrc', '.pgpass', '.npmrc', '.pypirc', '.git-credentials',
    'id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'id_ecdsa_sk', 'id_ed25519_sk',
    'credentials', 'credentials.json', 'service-account.json',
})
EXCLUDED_SUFFIXES = ('.pem', '.key', '.p12', '.pfx', '.jks', '.keystore', '.ppk', '.gpg')
PRIVATE_KEY_MARKER = re.compile(rb'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----')
SNIFF_BYTES = 8192

JOB_ID_RE = re.compile(r'^[0-9a-f]{32}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

EXIT_OK = 0
EXIT_JOB_FAILED = 1
EXIT_INVALID = 2
EXIT_STATUS_ERROR = 3
EXIT_TIMEOUT = 124
EXIT_CAMPAIGN_LIMIT = 4

# Who submitted a job (written beside request.json, never inside it, so the bridge and
# the ailab gateway see an unchanged request). An agent seat's environment carries
# OPENLABS_CAMPAIGN_ID (set by the lab runner); OPENLABS_CAMPAIGN_COMPUTE_THREADS is the
# topic's limit on CPU threads its queued + running jobs may declare at once.
SUBMITTER_FILE = 'submitter.json'
CAMPAIGN_ENV = 'OPENLABS_CAMPAIGN_ID'
CAMPAIGN_LIMIT_ENV = 'OPENLABS_CAMPAIGN_COMPUTE_THREADS'


class RemoteComputeError(Exception):
    """Invalid request, rejected source tree or unreadable queue state."""


# --------------------------------------------------------------------------- paths

def default_queue_root(environ: dict[str, str] | None = None) -> Path:
    """Queue root, independent of the current working directory."""
    env = os.environ if environ is None else environ
    configured = env.get('OPENLABS_REMOTE_QUEUE', '').strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise RemoteComputeError('OPENLABS_REMOTE_QUEUE must be an absolute path')
        return path
    if Path('/.dockerenv').exists():
        return CONTAINER_QUEUE
    home = env.get('HOME') or str(Path.home())
    return Path(home) / WSL_QUEUE_RELATIVE


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise RemoteComputeError(f'queue path is not a plain directory: {path}')
    os.chmod(path, 0o700)


def jobs_dir(queue_root: Path) -> Path:
    return queue_root / 'jobs'


def job_dir(queue_root: Path, job_id: str) -> Path:
    validate_job_id(job_id)
    return jobs_dir(queue_root) / job_id


def validate_job_id(job_id: str) -> str:
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        raise RemoteComputeError('job id must be 32 lowercase hex characters')
    return job_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _write_private_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _json_bytes(obj: Any) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + '\n').encode('utf-8')


# ------------------------------------------------------------------ validation

def _bounded_int(name: str, value: Any, bounds: tuple[int, int]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RemoteComputeError(f'{name} must be an integer')
    low, high = bounds
    if not low <= value <= high:
        raise RemoteComputeError(f'{name} must be between {low} and {high}, got {value}')
    return value


def validate_resources(cpu_threads: Any, memory_mib: Any, wall_seconds: Any) -> dict[str, int]:
    return {
        'cpu_threads': _bounded_int('cpu_threads', cpu_threads, CPU_RANGE),
        'memory_mib': _bounded_int('memory_mib', memory_mib, MEMORY_MIB_RANGE),
        'wall_seconds': _bounded_int('wall_seconds', wall_seconds, WALL_SECONDS_RANGE),
    }


def validate_argv(argv: Any) -> list[str]:
    """The command is an argv list executed as-is; shell text is never evaluated here."""
    if not isinstance(argv, (list, tuple)) or not argv:
        raise RemoteComputeError('command must be a non-empty argument list')
    for item in argv:
        if not isinstance(item, str) or not item or '\x00' in item:
            raise RemoteComputeError('every command argument must be a non-empty string without NUL')
    return list(argv)


def validate_backend(backend: Any) -> str:
    if backend not in BACKENDS:
        raise RemoteComputeError(f'backend must be one of {", ".join(BACKENDS)}')
    return backend


def safe_arcname(relative: str) -> str:
    """Archive entry name: relative POSIX path, no absolute part, no '.' or '..'."""
    if not relative or '\x00' in relative or '\\' in relative:
        raise RemoteComputeError('invalid archive entry name')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or relative.startswith('/'):
        raise RemoteComputeError('absolute archive entry rejected')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise RemoteComputeError('archive entry with empty, "." or ".." component rejected')
    return relative


# -------------------------------------------------------------------- payload

@dataclass
class SourceEntry:
    arcname: str
    path: Path
    is_dir: bool
    mode: int
    size: int
    mtime: int


@dataclass
class SourceScan:
    entries: list[SourceEntry] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    total_bytes: int = 0
    file_count: int = 0


def _looks_like_private_key(path: Path) -> bool:
    # Read only a prefix to classify the file; the contents are never printed.
    try:
        with path.open('rb') as handle:
            head = handle.read(SNIFF_BYTES)
    except OSError as exc:
        raise RemoteComputeError(f'cannot read source file {path.name}: {exc.strerror}') from None
    return bool(PRIVATE_KEY_MARKER.search(head))


def _is_excluded_file_name(name: str) -> bool:
    lowered = name.lower()
    if lowered == '.env' or lowered.startswith('.env.'):
        return True
    if lowered in EXCLUDED_FILE_NAMES:
        return True
    return lowered.endswith(EXCLUDED_SUFFIXES)


def scan_source(
    source: Path,
    *,
    max_bytes: int = MAX_PAYLOAD_SOURCE_BYTES,
    max_files: int = MAX_PAYLOAD_FILES,
) -> SourceScan:
    """Walk the source tree without following symlinks; reject anything not plain."""
    source = Path(source)
    if not source.is_absolute():
        source = Path(os.path.abspath(source))
    try:
        top = os.lstat(source)
    except FileNotFoundError:
        raise RemoteComputeError(f'source directory does not exist: {source}') from None
    if stat.S_ISLNK(top.st_mode):
        raise RemoteComputeError(f'source directory is a symlink: {source}')
    if not stat.S_ISDIR(top.st_mode):
        raise RemoteComputeError(f'source is not a directory: {source}')

    scan = SourceScan()

    def walk(directory: Path, prefix: str) -> None:
        try:
            names = sorted(os.listdir(directory))
        except OSError as exc:
            raise RemoteComputeError(f'cannot list {prefix or "."}: {exc.strerror}') from None
        for name in names:
            rel = f'{prefix}/{name}' if prefix else name
            path = directory / name
            st = os.lstat(path)
            mode = st.st_mode
            if stat.S_ISLNK(mode):
                raise RemoteComputeError(f'symlink rejected in source: {rel}')
            if stat.S_ISDIR(mode):
                if name in EXCLUDED_DIR_NAMES:
                    scan.excluded.append(rel + '/')
                    continue
                arc = safe_arcname(rel)
                scan.entries.append(SourceEntry(arc, path, True, stat.S_IMODE(mode), 0, int(st.st_mtime)))
                walk(path, rel)
                continue
            if not stat.S_ISREG(mode):
                raise RemoteComputeError(f'special file rejected in source: {rel}')
            if _is_excluded_file_name(name) or _looks_like_private_key(path):
                scan.excluded.append(rel)
                continue
            arc = safe_arcname(rel)
            scan.file_count += 1
            scan.total_bytes += st.st_size
            if scan.file_count > max_files:
                raise RemoteComputeError(f'source has more than {max_files} files')
            if scan.total_bytes > max_bytes:
                raise RemoteComputeError(f'source exceeds {max_bytes} bytes')
            scan.entries.append(SourceEntry(arc, path, False, stat.S_IMODE(mode), st.st_size, int(st.st_mtime)))

    walk(source, '')
    return scan


def _tarinfo(entry: SourceEntry) -> tarfile.TarInfo:
    info = tarfile.TarInfo(entry.arcname)
    # Keep rwx bits (including executable); drop setuid/setgid/sticky.
    info.mode = entry.mode & 0o777
    info.mtime = entry.mtime
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    if entry.is_dir:
        info.type = tarfile.DIRTYPE
        info.size = 0
    else:
        info.type = tarfile.REGTYPE
        info.size = entry.size
    return info


def write_payload(scan: SourceScan, destination: Path) -> tuple[str, int]:
    """Write payload.tar.gz atomically; return (sha256 hex, compressed bytes)."""
    fd, tmp = tempfile.mkstemp(prefix='.payload.', suffix='.tmp', dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as raw:
            with tarfile.open(fileobj=raw, mode='w:gz', format=tarfile.PAX_FORMAT) as archive:
                for entry in scan.entries:
                    info = _tarinfo(entry)
                    if entry.is_dir:
                        archive.addfile(info)
                        continue
                    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                    file_fd = os.open(entry.path, flags)
                    with os.fdopen(file_fd, 'rb') as handle:
                        current = os.fstat(handle.fileno())
                        if not stat.S_ISREG(current.st_mode) or current.st_size != entry.size:
                            raise RemoteComputeError(f'source file changed during packing: {entry.arcname}')
                        archive.addfile(info, handle)
            raw.flush()
            os.fsync(raw.fileno())
        digest = hashlib.sha256()
        size = 0
        with open(tmp, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
        os.replace(tmp, destination)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return digest.hexdigest(), size


# --------------------------------------------------------------------- submit

@dataclass
class Submission:
    job_id: str
    job_dir: Path
    request: dict[str, Any]
    excluded: list[str]


def submit(
    source: Path,
    argv: Sequence[str],
    *,
    cpu_threads: int,
    memory_mib: int,
    wall_seconds: int,
    backend: str = 'ailab',
    task_type: str = 'cpu',
    storage: str = 'auto',
    queue_root: Path | None = None,
    max_bytes: int = MAX_PAYLOAD_SOURCE_BYTES,
    max_files: int = MAX_PAYLOAD_FILES,
) -> Submission:
    argv = validate_argv(argv)
    resources = validate_resources(cpu_threads, memory_mib, wall_seconds)
    backend = validate_backend(backend)
    if task_type not in ('cpu', 'math'):
        raise RemoteComputeError('task_type must be cpu or math')
    if storage not in STORAGE_CHOICES:
        raise RemoteComputeError('storage must be auto or ssd1 through ssd6')
    scan = scan_source(Path(source), max_bytes=max_bytes, max_files=max_files)

    root = Path(queue_root) if queue_root is not None else default_queue_root()
    if not root.is_absolute():
        raise RemoteComputeError('queue root must be an absolute path')
    _ensure_private_dir(root)
    _ensure_private_dir(jobs_dir(root))

    job_id = uuid.uuid4().hex
    directory = job_dir(root, job_id)
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    try:
        sha256, payload_bytes = write_payload(scan, directory / 'payload.tar.gz')
        request = {
            'schema_version': SCHEMA_VERSION,
            'job_id': job_id,
            'backend': backend,
            'argv': argv,
            'resources': resources,
            'payload_sha256': sha256,
            'payload_bytes': payload_bytes,
            'created_at': utc_now(),
        }
        if task_type == 'math':
            request['task_type'] = 'math'
        if storage != 'auto':
            request['storage'] = storage
        _write_private_atomic(directory / 'request.json', _json_bytes(request))
        _write_private_atomic(directory / 'status.json', _json_bytes({
            'job_id': job_id, 'state': 'queued', 'updated_at': request['created_at'],
        }))
        write_submitter(directory)
        # READY last: its presence tells the bridge the job directory is complete.
        _write_private_atomic(directory / 'READY', (job_id + '\n').encode('ascii'))
    except BaseException:
        _remove_incomplete_job(directory)
        raise
    return Submission(job_id, directory, request, scan.excluded)


def _remove_incomplete_job(directory: Path) -> None:
    if (directory / 'READY').exists():
        return
    for child in directory.iterdir():
        if child.is_file() and not child.is_symlink():
            child.unlink()
    directory.rmdir()


# ------------------------------------------------------- per-topic queue limit

def submitter(environ: dict[str, str] | None = None) -> dict[str, str] | None:
    """The submitting topic from the agent environment (None outside an agent seat)."""
    env = os.environ if environ is None else environ
    campaign = str(env.get(CAMPAIGN_ENV) or '').strip()
    if not campaign:
        return None
    record = {'campaign_id': campaign}
    task = str(env.get('OPENLABS_TASK_ID') or '').strip()
    if task:
        record['task_id'] = task
    return record


def write_submitter(directory: Path, environ: dict[str, str] | None = None) -> None:
    record = submitter(environ)
    if record is not None:
        _write_private_atomic(directory / SUBMITTER_FILE,
                              _json_bytes({**record, 'submitted_at': utc_now()}))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def active_state(directory: Path) -> str | None:
    """'queued' (dispatchable: READY, not withdrawn) or 'running', else None.

    The same rule as the bridge's and the tick's load counts: a withdrawn job
    (``WITHDRAWN*``: moved to the local queue, or withdrawn by its submitter) and a
    queued job without READY are not in the queue.
    """
    status = _read_json(directory / 'status.json')
    state = status.get('state') if isinstance(status, dict) else None
    if state not in ('queued', 'running'):
        return None
    try:
        if any(directory.glob('WITHDRAWN*')):
            return None
    except OSError:
        return None
    if state == 'queued' and not (directory / 'READY').is_file():
        return None
    return state


def campaign_queue_load(campaign_id: str, roots: Sequence[Path], *, infer: bool = False,
                        attribution_roots: Sequence[Path] | None = None) -> dict[str, Any]:
    """Jobs of one topic still in the given queues (queued with READY, or running).

    A withdrawn ailab copy (moved to the local queue, abandoned) is not counted; the
    local copy of a moved job is. Jobs are the topic's by ``submitter.json``; with
    ``infer`` also older untagged jobs attributed to it by path or by a unique mention
    in its workspace (:func:`queue_jobs`).
    """
    load: dict[str, Any] = {'jobs': 0, 'queued': 0, 'running': 0, 'cpu_threads': 0,
                            'job_ids': [], 'inferred': 0, 'untagged_elsewhere': 0}
    listing = queue_jobs([('', Path(root)) for root in roots], attribute=infer,
                         attribution_roots=attribution_roots)
    for row in listing['jobs']:
        if row['campaign_id'] != campaign_id:
            if row['campaign_id'] is None:
                load['untagged_elsewhere'] += 1
            continue
        load['jobs'] += 1
        load[row['state']] += 1
        load['cpu_threads'] += row['cpu_threads']
        load['job_ids'].append(row['job_id'])
        if row['attribution'] != 'submitter':
            load['inferred'] += 1
    return load


# ------------------------------------------------------- attribution and listing

ATTRIBUTION_ROOTS_ENV = 'OPENLABS_JOB_ATTRIBUTION_ROOTS'
MENTION_SUFFIXES = frozenset({'.md', '.txt', '.json', '.jsonl', '.sh', '.log', '.yaml',
                              '.yml', '.toml'})
MENTION_MAX_FILE_BYTES = 256 * 1024
MENTION_MAX_DEPTH = 5
MENTION_TIME_BUDGET_SECONDS = 10.0
# One tick renders several briefs; the scan (about 4 s over the cc-sg workspaces on
# 2026-11-19) is reused within a process for this long.
MENTION_CACHE_SECONDS = 600.0
_MENTION_CACHE: dict[Any, tuple[float, dict[str, set[str]], bool]] = {}
_SAFE_TOKEN = re.compile(r'[^a-zA-Z0-9._-]+')


def default_attribution_roots(environ: dict[str, str] | None = None) -> list[Path]:
    """Workspace roots (``.../workspaces``; children ``DOMAIN/CAMPAIGN_ID``) used to
    attribute untagged jobs. ``OPENLABS_JOB_ATTRIBUTION_ROOTS`` (os.pathsep-separated;
    empty: none) overrides the instance's ``openlabs-data/workspaces``."""
    env = os.environ if environ is None else environ
    if ATTRIBUTION_ROOTS_ENV in env:
        return [Path(item) for item in str(env[ATTRIBUTION_ROOTS_ENV]).split(os.pathsep)
                if item.strip()]
    try:
        from .config import workspace_paths

        root = workspace_paths().data / 'workspaces'
    except Exception:  # noqa: BLE001 - attribution is best effort
        return []
    return [root] if root.is_dir() else []


def known_campaigns(roots: Sequence[Path]) -> dict[str, Path]:
    """campaign id -> canonical workspace directory, from ``ROOT/DOMAIN/CAMPAIGN_ID``."""
    found: dict[str, Path] = {}
    for root in roots:
        try:
            domains = [item for item in Path(root).iterdir() if item.is_dir()]
        except OSError:
            continue
        for domain in domains:
            try:
                children = sorted(item for item in domain.iterdir()
                                  if item.is_dir() and item.name != 'instances')
            except OSError:
                continue
            for child in children:
                found.setdefault(child.name, child)
    return found


def attempt_token(campaign_id: str) -> str:
    """The campaign's directory name under ``attempt-workspaces`` (attempts._token)."""
    cleaned = _SAFE_TOKEN.sub('-', campaign_id).strip('-._')[:48] or 'item'
    return f'{cleaned}-{hashlib.sha256(campaign_id.encode()).hexdigest()[:12]}'


def _path_campaign(texts: Sequence[str], tokens: dict[str, str]) -> str | None:
    for text in texts:
        for part in re.split(r'[/\s]+', str(text or '')):
            if part in tokens:
                return tokens[part]
    return None


def _mentions(job_ids: set[str], campaigns: dict[str, Path], *,
              budget_seconds: float = MENTION_TIME_BUDGET_SECONDS,
              clock: Callable[[], float] = time.monotonic) -> tuple[dict[str, set[str]], bool]:
    """job id -> campaigns whose workspace text files name it; False if the scan was cut
    short by its time budget."""
    found: dict[str, set[str]] = {job_id: set() for job_id in job_ids}
    if not job_ids:
        return found, True
    deadline = clock() + budget_seconds

    def walk(directory: Path, depth: int, campaign: str) -> bool:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError:
            return True
        for entry in entries:
            if clock() > deadline:
                return False
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if depth < MENTION_MAX_DEPTH and entry.name not in EXCLUDED_DIR_NAMES:
                        if not walk(Path(entry.path), depth + 1, campaign):
                            return False
                    continue
                if (not entry.is_file() or Path(entry.name).suffix.lower() not in MENTION_SUFFIXES
                        or entry.stat().st_size > MENTION_MAX_FILE_BYTES):
                    continue
                with open(entry.path, 'rb') as handle:
                    data = handle.read()
            except OSError:
                continue
            for match in pattern.findall(data):
                found[match.decode('ascii')].add(campaign)
        return True

    pattern = re.compile(b'|'.join(re.escape(job_id.encode('ascii'))
                                   for job_id in sorted(job_ids)))

    for campaign, directory in campaigns.items():
        if not walk(directory, 0, campaign):
            return found, False
    return found, True


def _payload_top(path: Path) -> str | None:
    """First top-level entry of an ailab payload (its source directory's layout)."""
    try:
        with tarfile.open(path, mode='r|gz') as archive:
            for member in archive:
                top = member.name.split('/')[0]
                return top + '/' if member.isdir() or '/' in member.name else top
    except (OSError, tarfile.TarError, EOFError):
        return None
    return None


def queue_jobs(roots: Sequence[tuple[str, Path]], *, attribute: bool = True,
               attribution_roots: Sequence[Path] | None = None,
               environ: dict[str, str] | None = None) -> dict[str, Any]:
    """Queued (dispatchable) and running jobs of the given queues, each attributed to a
    topic.

    ``roots`` are ``(backend, queue root)`` pairs (an empty backend is read from the
    job's request). ``attribution`` per job:

    - ``submitter``: ``submitter.json`` (jobs submitted from an agent seat since
      2026-11-18);
    - ``source_path``: the local job's source directory, a moved job's origin or the
      command names the campaign's workspace or attempt-workspace directory;
    - ``workspace_mention``: only that campaign's workspace text files (handover, work
      log, notes) name the job id;
    - ``ambiguous`` (several campaigns name it; ``candidates``) or ``unknown``.

    Without ``attribute`` only ``submitter.json`` is read.
    """
    rows: list[dict[str, Any]] = []
    for backend, root in roots:
        try:
            directories = sorted(item for item in (Path(root) / 'jobs').iterdir()
                                 if item.is_dir() and JOB_ID_RE.match(item.name))
        except OSError:
            continue
        for directory in directories:
            state = active_state(directory)
            if state is None:
                continue
            request = _read_json(directory / 'request.json')
            request = request if isinstance(request, dict) else {}
            resources = request.get('resources') if isinstance(request.get('resources'),
                                                               dict) else {}
            try:
                threads = int(resources.get('cpu_threads') or 0)
                memory = int(resources.get('memory_mib') or 0)
            except (TypeError, ValueError):
                threads = memory = 0
            record = _read_json(directory / SUBMITTER_FILE)
            campaign = (str(record.get('campaign_id') or '') or None
                        if isinstance(record, dict) else None)
            moved = request.get('moved_from') if isinstance(request.get('moved_from'),
                                                            dict) else {}
            source = request.get('source')
            if not source and (directory / 'payload.tar.gz').is_file():
                top = _payload_top(directory / 'payload.tar.gz')
                source = f'payload: {top}' if top else None
            rows.append({
                'job_id': directory.name,
                'backend': backend or str(request.get('backend') or 'ailab'),
                'state': state,
                'cpu_threads': threads,
                'memory_mib': memory,
                'wall_seconds': resources.get('wall_seconds'),
                'created_at': request.get('created_at'),
                'submitted_task': record.get('task_id') if isinstance(record, dict) else None,
                'campaign_id': campaign,
                'attribution': 'submitter' if campaign else 'unknown',
                'source': source,
                'argv': [str(item) for item in request.get('argv') or []][:6],
                '_paths': [str(request.get('source') or ''), str(moved.get('job_dir') or ''),
                           *[str(item) for item in request.get('argv') or []]],
                'job_dir': str(directory),
            })
    complete = True
    untagged = [row for row in rows if row['campaign_id'] is None]
    if attribute and untagged:
        campaigns = known_campaigns(attribution_roots if attribution_roots is not None
                                    else default_attribution_roots(environ))
        tokens = {**{attempt_token(cid): cid for cid in campaigns},
                  **{cid: cid for cid in campaigns}}
        for row in untagged:
            campaign = _path_campaign(row['_paths'], tokens)
            if campaign:
                row['campaign_id'], row['attribution'] = campaign, 'source_path'
        remaining = {row['job_id'] for row in untagged if row['campaign_id'] is None}
        key = (frozenset(remaining), tuple(sorted(str(path) for path in campaigns.values())))
        cached = _MENTION_CACHE.get(key)
        if cached is not None and time.monotonic() - cached[0] < MENTION_CACHE_SECONDS:
            mentions, complete = cached[1], cached[2]
        else:
            mentions, complete = _mentions(remaining, campaigns)
            _MENTION_CACHE.clear()
            _MENTION_CACHE[key] = (time.monotonic(), mentions, complete)
        for row in untagged:
            names = sorted(mentions.get(row['job_id']) or ())
            if row['campaign_id'] is not None or not names:
                continue
            if len(names) == 1:
                row['campaign_id'], row['attribution'] = names[0], 'workspace_mention'
            else:
                row['attribution'], row['candidates'] = 'ambiguous', names
    for row in rows:
        row.pop('_paths', None)
    rows.sort(key=lambda row: (str(row.get('created_at') or ''), row['job_id']))
    return {'jobs': rows, 'attribution_complete': complete}


def default_roots(environ: dict[str, str] | None = None) -> list[tuple[str, Path]]:
    from .local_compute import default_queue_root as local_root

    env = os.environ if environ is None else environ
    return [('ailab', default_queue_root(env)), ('local', local_root(env))]


# ------------------------------------------------------------------- withdraw

WITHDRAWN_BY_SUBMITTER = 'WITHDRAWN.by-submitter'
# The bridge (tools/remote-compute/bridge.py) takes a job by writing state "running"
# to status.json (after hashing the payload) and opening transport.log; it keeps READY
# until the job ends. The local dispatcher likewise writes "running" before starting.
# A job is withdrawn by renaming READY away; a dispatcher that had already picked it up
# shows itself within this many seconds, and the withdrawal is then rolled back.
WITHDRAW_SETTLE_SECONDS = 5.0
EXIT_NOT_WITHDRAWN = 5


def _taken(directory: Path) -> str | None:
    """Why the dispatcher already owns this job (None: still only queued)."""
    status = _read_json(directory / 'status.json')
    state = status.get('state') if isinstance(status, dict) else None
    if state != 'queued':
        return f'state is {state or "unreadable"}'
    if (directory / 'transport.log').exists():
        return 'the bridge has started transferring it (transport.log)'
    return None


def withdraw(job_ids: Sequence[str], *, reason: str = '', any_topic: bool = False,
             queue_root: Path | None = None, local_root: Path | None = None,
             environ: dict[str, str] | None = None,
             attribution_roots: Sequence[Path] | None = None,
             settle_seconds: float = WITHDRAW_SETTLE_SECONDS,
             sleep: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:
    """Withdraw still-queued jobs before a dispatcher takes them.

    Per job: refuse unless it is queued with READY, not withdrawn, not in transfer, and
    (without ``any_topic``) not tagged or attributed to another topic than the caller's
    ``OPENLABS_CAMPAIGN_ID``. Then write ``WITHDRAWN.by-submitter`` (who, when, why) and
    atomically rename READY -> READY.withdrawn; after ``settle_seconds`` re-check, and
    roll a job back (READY restored, marker removed) if a dispatcher took it meanwhile.
    Returns one ``{job_id, withdrawn, ...}`` record per id.
    """
    from .local_compute import default_queue_root as local_default, locate

    env = os.environ if environ is None else environ
    remote_root = Path(queue_root) if queue_root is not None else default_queue_root(env)
    local_root = Path(local_root) if local_root is not None else local_default(env)
    me = submitter(env)
    results: list[dict[str, Any]] = []
    pending: list[tuple[dict[str, Any], Path]] = []
    attributed: dict[str, dict[str, Any]] | None = None
    for job_id in job_ids:
        outcome: dict[str, Any] = {'job_id': job_id, 'withdrawn': False}
        results.append(outcome)
        if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
            outcome['error'] = 'job id must be 32 lowercase hex characters'
            continue
        backend, directory = locate(job_id, remote_root, local_root)
        outcome['backend'] = backend
        if not (directory / 'request.json').is_file():
            outcome['error'] = 'no such job in either queue'
            continue
        if any(directory.glob('WITHDRAWN*')):
            outcome['error'] = 'already withdrawn'
            continue
        taken = _taken(directory)
        if taken:
            outcome['error'] = (f'not withdrawable: {taken}; a running or finished job is '
                                'not stopped by withdraw')
            continue
        if not (directory / 'READY').is_file():
            outcome['error'] = 'not withdrawable: not dispatchable (no READY)'
            continue
        record = _read_json(directory / SUBMITTER_FILE)
        owner = record.get('campaign_id') if isinstance(record, dict) else None
        how = 'submitter' if owner else 'unknown'
        if not owner:
            if attributed is None:
                listing = queue_jobs([('ailab', remote_root), ('local', local_root)],
                                     attribution_roots=attribution_roots, environ=env)
                attributed = {row['job_id']: row for row in listing['jobs']}
            row = attributed.get(job_id) or {}
            owner, how = row.get('campaign_id'), row.get('attribution') or 'unknown'
        outcome['campaign_id'], outcome['attribution'] = owner, how
        if (not any_topic and me is not None and owner is not None
                and owner != me['campaign_id']):
            outcome['error'] = (f'job belongs to another topic ({owner}, by {how}); '
                                'pass --any-topic only if that is intended')
            continue
        marker = directory / WITHDRAWN_BY_SUBMITTER
        _write_private_atomic(marker, _json_bytes({
            'job_id': job_id, 'withdrawn_at': utc_now(), 'backend': backend,
            'by': me or {'campaign_id': None},
            'reason': reason, 'campaign_id': owner, 'attribution': how,
        }))
        try:
            os.rename(directory / 'READY', directory / 'READY.withdrawn')
        except OSError:
            marker.unlink(missing_ok=True)
            outcome['error'] = 'not withdrawable: READY vanished (taken or withdrawn concurrently)'
            continue
        pending.append((outcome, directory))
    if pending and settle_seconds > 0:
        sleep(settle_seconds)
    for outcome, directory in pending:
        taken = _taken(directory)
        if taken:
            (directory / WITHDRAWN_BY_SUBMITTER).unlink(missing_ok=True)
            try:
                os.rename(directory / 'READY.withdrawn', directory / 'READY')
            except OSError:
                pass
            outcome['error'] = f'taken by the dispatcher while withdrawing ({taken}); left as is'
            continue
        outcome['withdrawn'] = True
    return results


def _short_campaign(campaign: str | None) -> str:
    if not campaign:
        return '-'
    match = re.search(r'candidate-topic-([0-9a-f]+)', campaign)
    return f'topic-{match.group(1)[:8]}' if match else campaign[:40]


def campaign_limit_problem(cpu_threads: int, environ: dict[str, str] | None = None,
                           roots: Sequence[Path] | None = None) -> str | None:
    """Why this topic may not queue another job now (None: it may).

    The limit counts the CPU threads declared by the topic's jobs still queued or
    running on ailab and in the local queue. A topic with nothing in the queues may
    always submit one job, however large.
    """
    env = os.environ if environ is None else environ
    record = submitter(env)
    try:
        limit = int(str(env.get(CAMPAIGN_LIMIT_ENV) or '0').strip() or 0)
    except ValueError:
        limit = 0
    if record is None or limit <= 0:
        return None
    if roots is None:
        from .local_compute import default_queue_root as local_root
        roots = (default_queue_root(env), local_root(env))
    load = campaign_queue_load(record['campaign_id'], roots, infer=True,
                               attribution_roots=default_attribution_roots(env))
    if load['cpu_threads'] == 0 or load['cpu_threads'] + cpu_threads <= limit:
        return None
    shown = ', '.join(load['job_ids'][:6]) + (' ...' if len(load['job_ids']) > 6 else '')
    return (
        f'per-topic compute limit: this topic already has {load["jobs"]} job(s) in the '
        f'queues ({load["running"]} running, {load["queued"]} queued) declaring '
        f'{load["cpu_threads"]} CPU thread(s); limit {limit} ({CAMPAIGN_LIMIT_ENV}), this job '
        f'asks for {cpu_threads}. Not submitted. Do not retry in a loop: wait for those jobs '
        f'(openlabs-remote wait JOB_ID, or end the seat as awaiting_remote with their ids: '
        f'{shown}) and submit the next batch from their results. Split large profile or '
        f'sweep sets into batches, coarse first, so each batch decides the next. '
        f'`openlabs-remote list --mine` shows them; `openlabs-remote withdraw JOB_ID... '
        f'--reason TEXT` takes back queued ones that matter less.'
    )


# --------------------------------------------------------------- status/wait

def locate_job(job_id: str, queue_root: Path | None = None) -> tuple[str, Path]:
    """(backend, job directory): ailab queue first, else the local overflow queue; an
    ailab job moved to the container (``WITHDRAWN.moved-to-local``) resolves locally."""
    from .local_compute import locate

    validate_job_id(job_id)
    root = Path(queue_root) if queue_root is not None else default_queue_root()
    return locate(job_id, root)


def read_status(job_id: str, queue_root: Path | None = None) -> dict[str, Any]:
    backend, directory = locate_job(job_id, queue_root)
    root = directory.parent.parent
    path = directory / 'status.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise RemoteComputeError(f'no status for job {job_id} under {jobs_dir(root)}') from None
    except (OSError, ValueError) as exc:
        raise RemoteComputeError(f'unreadable status for job {job_id}: {exc}') from None
    if not isinstance(data, dict):
        raise RemoteComputeError(f'status for job {job_id} is not a JSON object')
    if data.get('job_id') != job_id:
        raise RemoteComputeError(f'status job_id mismatch for {job_id}')
    if data.get('state') not in STATES:
        raise RemoteComputeError(f'status for job {job_id} has unknown state {data.get("state")!r}')
    receipt = data.get('receipt_sha256')
    if receipt is not None and not (isinstance(receipt, str) and SHA256_RE.match(receipt)):
        raise RemoteComputeError(f'status for job {job_id} has malformed receipt_sha256')
    if backend == 'local':
        data = {**data, 'backend': 'local', 'result_dir': str(directory / 'result')}
    return data


@dataclass
class WaitResult:
    status: dict[str, Any] | None
    timed_out: bool


def wait_for(
    job_id: str,
    *,
    timeout_seconds: float | None = None,
    queue_root: Path | None = None,
    poll_seconds: float = POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> WaitResult:
    validate_job_id(job_id)
    deadline = None if timeout_seconds is None else clock() + timeout_seconds
    status = None
    while True:
        status = read_status(job_id, queue_root)
        if status['state'] in TERMINAL_STATES:
            return WaitResult(status, False)
        if deadline is not None:
            remaining = deadline - clock()
            if remaining <= 0:
                return WaitResult(status, True)
            sleep(min(poll_seconds, remaining))
        else:
            sleep(poll_seconds)


# ------------------------------------------------------------------------ CLI

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='openlabs-remote',
        description='Submit CPU jobs to the OpenLabs remote compute queue (run inside the resource guard).',
    )
    sub = parser.add_subparsers(dest='action', required=True)
    s = sub.add_parser('submit', usage='openlabs-remote submit --source DIR --cpus N --memory-mib N '
                       '--timeout-seconds N [--backend auto|ailab|local] -- COMMAND [ARGS...]')
    s.add_argument('--source', required=True)
    s.add_argument('--cpus', required=True, type=int)
    s.add_argument('--memory-mib', required=True, type=int)
    s.add_argument('--timeout-seconds', required=True, type=int)
    s.add_argument('--backend', default='auto', choices=CLI_BACKENDS)
    s.add_argument('--task-type', default='cpu', choices=('cpu', 'math'))
    s.add_argument('--storage', default='auto', choices=STORAGE_CHOICES)
    st = sub.add_parser('status')
    st.add_argument('job_id')
    w = sub.add_parser('wait')
    w.add_argument('job_id')
    w.add_argument('--timeout-seconds', type=float, default=None)
    ls = sub.add_parser('list', help='queued and running jobs of both queues, by topic')
    who = ls.add_mutually_exclusive_group()
    who.add_argument('--mine', action='store_true',
                     help=f'only this seat\'s topic (${CAMPAIGN_ENV})')
    who.add_argument('--campaign', metavar='ID')
    ls.add_argument('--json', action='store_true')
    wd = sub.add_parser('withdraw', help='take back still-queued jobs (not running ones)')
    wd.add_argument('job_ids', nargs='+', metavar='JOB_ID')
    wd.add_argument('--reason', default='')
    wd.add_argument('--any-topic', action='store_true',
                    help='allow jobs tagged or attributed to another topic')
    return parser


def _list_command(args: argparse.Namespace) -> int:
    campaign = args.campaign
    if args.mine:
        record = submitter()
        if record is None:
            print(f'openlabs-remote list --mine: {CAMPAIGN_ENV} is not set', file=sys.stderr)
            return EXIT_INVALID
        campaign = record['campaign_id']
    listing = queue_jobs(default_roots())
    rows = [row for row in listing['jobs'] if campaign is None or row['campaign_id'] == campaign]
    if args.json:
        _print_json({'campaign_id': campaign, 'jobs': rows,
                     'attribution_complete': listing['attribution_complete']})
        return EXIT_OK
    print(f'{"JOB_ID":32}  {"BACKEND":7} {"STATE":7} {"THR":>3} {"MEM_MIB":>7}  '
          f'{"CREATED":25} {"TOPIC":14} {"BY":17} SOURCE')
    for row in rows:
        print(f'{row["job_id"]:32}  {row["backend"]:7} {row["state"]:7} '
              f'{row["cpu_threads"]:>3} {row["memory_mib"]:>7}  '
              f'{str(row["created_at"] or "-")[:25]:25} {_short_campaign(row["campaign_id"]):14} '
              f'{row["attribution"]:17} {row["source"] or " ".join(row["argv"])}')
    totals: dict[str | None, list[int]] = {}
    for row in rows:
        total = totals.setdefault(row['campaign_id'], [0, 0, 0])
        total[0] += 1
        total[1] += row['state'] == 'queued'
        total[2] += row['cpu_threads']
    print()
    for key, (jobs, queued, threads) in sorted(totals.items(), key=lambda item: str(item[0])):
        print(f'{key or "unattributed"}: {jobs} job(s), {queued} queued, {threads} thread(s)')
    limit = str(os.environ.get(CAMPAIGN_LIMIT_ENV) or '').strip()
    if args.mine and limit:
        print(f'limit: {limit} thread(s) queued + running for this topic ({CAMPAIGN_LIMIT_ENV})')
    if not listing['attribution_complete']:
        print('note: the workspace scan for untagged jobs stopped at its time budget',
              file=sys.stderr)
    return EXIT_OK


def _withdraw_command(args: argparse.Namespace) -> int:
    results = withdraw(args.job_ids, reason=args.reason, any_topic=args.any_topic)
    for outcome in results:
        if outcome['withdrawn']:
            print(f'withdrawn: {outcome["job_id"]} ({outcome.get("backend")})')
        else:
            print(f'not withdrawn: {outcome["job_id"]}: {outcome.get("error")}', file=sys.stderr)
    return EXIT_OK if all(item['withdrawn'] for item in results) else EXIT_NOT_WITHDRAWN


def _submit_routed(args: argparse.Namespace, command: list[str]) -> int | None:
    """`auto`/`local` submissions: None means "submit to ailab as usual"."""
    from . import local_compute

    argv = validate_argv(command)
    resources = validate_resources(args.cpus, args.memory_mib, args.timeout_seconds)
    if args.task_type not in ('cpu', 'math'):
        raise RemoteComputeError('task_type must be cpu or math')
    if args.storage not in STORAGE_CHOICES:
        raise RemoteComputeError('storage must be auto or ssd1 through ssd6')
    scan = scan_source(Path(args.source))
    if args.backend == 'local':
        if args.task_type != 'cpu' or args.storage != 'auto':
            raise RemoteComputeError('--backend local takes CPU jobs with default storage only')
        decision: dict[str, Any] = {'backend': 'local', 'reason': 'requested --backend local',
                                    'decided_at': utc_now()}
    else:
        decision = local_compute.overflow_decision(
            cpu_threads=resources['cpu_threads'], memory_mib=resources['memory_mib'],
            task_type=args.task_type, storage=args.storage,
            texts=local_compute.scan_texts(scan, argv), argv=argv,
            remote_root=default_queue_root(),
        )
        if decision['backend'] != 'local':
            print(f'routing: ailab ({decision["reason"]})', file=sys.stderr)
            for problem in decision.get('not_portable') or []:
                print(f'  not portable: {problem}', file=sys.stderr)
            return None
    job_id = local_compute.submit(
        Path(args.source), argv, cpu_threads=resources['cpu_threads'],
        memory_mib=resources['memory_mib'], wall_seconds=resources['wall_seconds'],
        scan=scan, routing=decision,
    )
    for name in scan.excluded:
        print(f'excluded: {name}', file=sys.stderr)
    print(f'routing: local ({decision["reason"]}); starts at the next orchestrator tick',
          file=sys.stderr)
    print(f'job_id: {job_id}')
    print(f'job_dir: {local_compute.default_queue_root() / "jobs" / job_id}')
    print('backend: local')
    return EXIT_OK


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if args_list and args_list[0] == 'submit':
        if '--' not in args_list:
            print('openlabs-remote submit: the command must follow "--"', file=sys.stderr)
            return EXIT_INVALID
        split = args_list.index('--')
        args_list, command = args_list[:split], args_list[split + 1:]
    args = _parser().parse_args(args_list)

    try:
        if args.action == 'submit':
            problem = campaign_limit_problem(args.cpus)
            if problem is not None:
                print(f'openlabs-remote: {problem}', file=sys.stderr)
                return EXIT_CAMPAIGN_LIMIT
        if args.action == 'submit' and args.backend != 'ailab':
            routed = _submit_routed(args, command)
            if routed is not None:
                return routed
        if args.action == 'submit':
            result = submit(
                Path(args.source), command,
                cpu_threads=args.cpus, memory_mib=args.memory_mib,
                wall_seconds=args.timeout_seconds, backend='ailab',
                task_type=args.task_type,
                storage=args.storage,
            )
            for name in result.excluded:
                print(f'excluded: {name}', file=sys.stderr)
            print(f'job_id: {result.job_id}')
            print(f'job_dir: {result.job_dir}')
            print('backend: ailab')
            return EXIT_OK
        if args.action == 'list':
            return _list_command(args)
        if args.action == 'withdraw':
            return _withdraw_command(args)
        if args.action == 'status':
            _print_json(read_status(args.job_id))
            return EXIT_OK
        if args.action == 'wait':
            outcome = wait_for(args.job_id, timeout_seconds=args.timeout_seconds)
            _print_json(outcome.status)
            if outcome.timed_out:
                print(f'timed out waiting for job {args.job_id}; the job directory is kept', file=sys.stderr)
                return EXIT_TIMEOUT
            if outcome.status['state'] == 'failed':
                result_dir = locate_job(args.job_id)[1] / 'result'
                print(f'job {args.job_id} failed; outputs kept under {result_dir}', file=sys.stderr)
                return EXIT_JOB_FAILED
            return EXIT_OK
    except RemoteComputeError as exc:
        print(f'openlabs-remote: {exc}', file=sys.stderr)
        return EXIT_INVALID if args.action == 'submit' else EXIT_STATUS_ERROR
    return EXIT_INVALID


if __name__ == '__main__':
    raise SystemExit(main())
