"""Local background compute queue: overflow for ailab, run in this container.

ailab is the preferred place for long CPU jobs and should be kept full; when its queue
is already saturated (for example two solves running and more queued), a job may run
here instead, in the background, inside the aggregate resource guard
(``bin/openlabs-resource-guard``). The layout mirrors the remote queue so the
orchestrator's yield-to-wait mechanism (``openlabs.remote_wait``) covers both::

    jobs/JOB_ID/request.json   backend "local", argv, resources, created_at
    jobs/JOB_ID/status.json    {job_id, state, updated_at, pid?, exit_code?, error?}
    jobs/JOB_ID/source/        snapshot of the submitted source directory
    jobs/JOB_ID/result/        stdout.log, stderr.log, outputs/ ($OPENLABS_OUTPUT_DIR)
    jobs/JOB_ID/READY          written last; presence = dispatchable

Jobs never start at submission. ``dispatch`` (each orchestrator tick, or
``bin/openlabs-local dispatch``) starts queued jobs while fewer than
``max_jobs`` (default 2) run and their declared CPUs fit ``max_cpus`` (default 8 of the
container's 15). Each job runs detached in its own session and records its own end.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .remote_compute import (
    EXCLUDED_DIR_NAMES,
    JOB_ID_RE,
    RemoteComputeError,
    _write_private_atomic,
    validate_argv,
    validate_resources,
)

DEFAULT_MAX_JOBS = 2
DEFAULT_MAX_CPUS = 8
STARTUP_GRACE_SECONDS = 120
TERMINAL_STATES = ('succeeded', 'failed')
CODE_ROOT = Path(__file__).resolve().parents[3]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_queue_root(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    configured = env.get('OPENLABS_LOCAL_QUEUE', '').strip()
    if configured:
        return Path(configured).expanduser()
    return Path('/workspace/.openlabs-local-compute')


def limits(environ: dict[str, str] | None = None) -> tuple[int, int]:
    env = os.environ if environ is None else environ

    def number(name: str, default: int) -> int:
        try:
            return max(1, int(env.get(name, '') or default))
        except ValueError:
            return default

    return number('OPENLABS_LOCAL_MAX_JOBS', DEFAULT_MAX_JOBS), number(
        'OPENLABS_LOCAL_MAX_CPUS', DEFAULT_MAX_CPUS)


def _json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_status(directory: Path, **fields: Any) -> dict[str, Any]:
    status = {**(_json(directory / 'status.json') or {}), **fields,
              'job_id': directory.name, 'updated_at': utc_now()}
    _write_private_atomic(directory / 'status.json',
                          (json.dumps(status, indent=2, sort_keys=True) + '\n').encode())
    return status


def submit(source: Path, argv: Sequence[str], *, cpu_threads: int, memory_mib: int,
           wall_seconds: int, queue_root: Path | None = None) -> str:
    argv = validate_argv(list(argv))
    resources = validate_resources(cpu_threads, memory_mib, wall_seconds)
    source = Path(source).resolve()
    if not source.is_dir():
        raise RemoteComputeError(f'source is not a directory: {source}')
    root = Path(queue_root) if queue_root is not None else default_queue_root()
    job_id = uuid.uuid4().hex
    directory = root / 'jobs' / job_id
    directory.mkdir(parents=True, mode=0o700)
    shutil.copytree(source, directory / 'source', symlinks=False,
                    ignore=shutil.ignore_patterns(*EXCLUDED_DIR_NAMES, '*.pyc'))
    request = {'schema_version': 'openlabs.local-compute.v1', 'job_id': job_id,
               'backend': 'local', 'argv': argv, 'resources': resources,
               'source': str(source), 'created_at': utc_now()}
    _write_private_atomic(directory / 'request.json',
                          (json.dumps(request, indent=2, sort_keys=True) + '\n').encode())
    _write_status(directory, state='queued')
    _write_private_atomic(directory / 'READY', (job_id + '\n').encode())
    return job_id


def _alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


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


def dispatch(queue_root: Path | None = None, *, max_jobs: int | None = None,
             max_cpus: int | None = None, launch: bool = True) -> dict[str, Any]:
    """Reap dead runners and start queued jobs within the local limits."""

    root = Path(queue_root) if queue_root is not None else default_queue_root()
    default_jobs, default_cpus = limits()
    max_jobs = max_jobs or default_jobs
    max_cpus = max_cpus or default_cpus
    summary: dict[str, Any] = {'started': [], 'reaped': [], 'running': 0, 'queued': 0}
    running_cpus = running = 0
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
                              'recording a result (container restart?)')
                summary['reaped'].append(directory.name)
                continue
            running += 1
            running_cpus += int(request['resources']['cpu_threads'])
        elif state == 'queued':
            queued.append((directory, request))
    for directory, request in queued:
        cpus = int(request['resources']['cpu_threads'])
        if not launch or running >= max_jobs or running_cpus + cpus > max_cpus:
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
        summary['started'].append(directory.name)
    summary['running'] = running
    summary['queued'] = sum(1 for _, _, status in _jobs(root) if status.get('state') == 'queued')
    return summary


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
           'OPENLABS_JOB_CPUS': threads, 'OPENLABS_JOB_ID': job_id}
    command = [str(CODE_ROOT / 'bin' / 'openlabs-resource-guard'), '--task-type', 'cpu', '--',
               *request.get('argv', [])]
    _write_status(directory, state='running', runner_pid=os.getpid(), started_at=utc_now())
    with open(result / 'stdout.log', 'wb') as out, open(result / 'stderr.log', 'wb') as err:
        try:
            completed = subprocess.run(command, cwd=directory / 'source', env=env, stdout=out,
                                       stderr=err, timeout=int(resources.get('wall_seconds') or 1),
                                       check=False)
            code, error = completed.returncode, None
        except subprocess.TimeoutExpired:
            code, error = 124, f"timed out after {resources.get('wall_seconds')} s"
        except OSError as exc:
            code, error = 127, str(exc)
    state = 'succeeded' if code == 0 else 'failed'
    _write_status(directory, state=state, exit_code=code, finished_at=utc_now(),
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
    r = sub.add_parser('run')
    r.add_argument('job_id')
    r.add_argument('--queue-root')
    args = parser.parse_args(args_list)
    try:
        if args.action == 'submit':
            job_id = submit(Path(args.source), command, cpu_threads=args.cpus,
                            memory_mib=args.memory_mib, wall_seconds=args.timeout_seconds)
            started = dispatch()
            print(f'job_id: {job_id}')
            print(f'job_dir: {default_queue_root() / "jobs" / job_id}')
            print(f'started now: {job_id in started["started"]}')
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
        if args.action == 'run':
            return run(args.job_id, Path(args.queue_root) if args.queue_root else None)
    except RemoteComputeError as exc:
        print(f'openlabs-local: {exc}', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
