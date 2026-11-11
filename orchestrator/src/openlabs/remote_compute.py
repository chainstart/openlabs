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


# --------------------------------------------------------------- status/wait

def read_status(job_id: str, queue_root: Path | None = None) -> dict[str, Any]:
    root = Path(queue_root) if queue_root is not None else default_queue_root()
    path = job_dir(root, job_id) / 'status.json'
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
                       '--timeout-seconds N [--backend ailab] -- COMMAND [ARGS...]')
    s.add_argument('--source', required=True)
    s.add_argument('--cpus', required=True, type=int)
    s.add_argument('--memory-mib', required=True, type=int)
    s.add_argument('--timeout-seconds', required=True, type=int)
    s.add_argument('--backend', default='ailab', choices=BACKENDS)
    s.add_argument('--task-type', default='cpu', choices=('cpu', 'math'))
    s.add_argument('--storage', default='auto', choices=STORAGE_CHOICES)
    st = sub.add_parser('status')
    st.add_argument('job_id')
    w = sub.add_parser('wait')
    w.add_argument('job_id')
    w.add_argument('--timeout-seconds', type=float, default=None)
    return parser


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
            result = submit(
                Path(args.source), command,
                cpu_threads=args.cpus, memory_mib=args.memory_mib,
                wall_seconds=args.timeout_seconds, backend=args.backend,
                task_type=args.task_type,
                storage=args.storage,
            )
            for name in result.excluded:
                print(f'excluded: {name}', file=sys.stderr)
            print(f'job_id: {result.job_id}')
            print(f'job_dir: {result.job_dir}')
            return EXIT_OK
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
                result_dir = job_dir(default_queue_root(), args.job_id) / 'result'
                print(f'job {args.job_id} failed; outputs kept under {result_dir}', file=sys.stderr)
                return EXIT_JOB_FAILED
            return EXIT_OK
    except RemoteComputeError as exc:
        print(f'openlabs-remote: {exc}', file=sys.stderr)
        return EXIT_INVALID if args.action == 'submit' else EXIT_STATUS_ERROR
    return EXIT_INVALID


if __name__ == '__main__':
    raise SystemExit(main())
