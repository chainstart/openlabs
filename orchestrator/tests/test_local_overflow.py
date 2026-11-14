"""Automatic ailab -> container overflow at the submit entry (openlabs.local_compute)."""

import json
import os
import stat
from pathlib import Path

import pytest

from openlabs import local_compute as lc
from openlabs import remote_compute as rc
from openlabs import remote_wait

CAPS = {'enabled': True, 'cpu_threads': 8, 'memory_mib': 62961, 'max_concurrent_jobs': 8}


@pytest.fixture
def queues(tmp_path, monkeypatch):
    remote, local = tmp_path / 'remote', tmp_path / 'local'
    monkeypatch.setenv('OPENLABS_REMOTE_QUEUE', str(remote))
    monkeypatch.setenv('OPENLABS_LOCAL_QUEUE', str(local))
    for name in ('OPENLABS_COMPUTE_OVERFLOW', 'OPENLABS_LOCAL_MAX_JOBS',
                 'OPENLABS_LOCAL_MAX_CPUS', 'OPENLABS_LOCAL_MAX_MEMORY_MIB'):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / 'local-compute.json'
    config.write_text(json.dumps({'max_jobs': 3, 'max_cpus': 8, 'max_memory_mib': 16384,
                                  'min_free_memory_mib': 8192}))
    remote_config = tmp_path / 'remote-compute.json'
    remote_config.write_text(json.dumps(CAPS))
    monkeypatch.setattr(lc, 'CONFIG_PATH', config)
    monkeypatch.setattr(lc, 'REMOTE_CONFIG_PATH', remote_config)
    monkeypatch.setattr(lc, '_container_free_memory_mib', lambda: 30000)
    return remote, local, config


def _source(tmp_path: Path, script: str = 'print("ok")\n', name: str = 'src') -> Path:
    src = tmp_path / name
    src.mkdir()
    (src / 'run.py').write_text(script)
    (src / 'data.csv').write_text('a,b\n1,2\n')
    return src


def _ailab_job(remote: Path, tmp_path: Path, state: str, cpus: int = 4) -> str:
    src = tmp_path / f'ailab-{state}-{len(list(tmp_path.iterdir()))}'
    src.mkdir()
    (src / 'run.py').write_text('print(1)\n')
    job = rc.submit(src, ['python3', 'run.py'], cpu_threads=cpus, memory_mib=8192,
                    wall_seconds=3600, queue_root=remote).job_id
    if state != 'queued':
        status = remote / 'jobs' / job / 'status.json'
        status.write_text(json.dumps({'job_id': job, 'state': state, 'updated_at': rc.utc_now()}))
    return job


def _fill_ailab(remote: Path, tmp_path: Path) -> None:
    _ailab_job(remote, tmp_path, 'running')
    _ailab_job(remote, tmp_path, 'running')


def _decide(remote, local, texts=None, **kwargs):
    params = dict(cpu_threads=4, memory_mib=8192, task_type='cpu', storage='auto',
                  texts=texts or {'run.py': 'print(1)\n'}, argv=['python3', 'run.py'],
                  remote_root=remote, local_root=local)
    params.update(kwargs)
    return lc.overflow_decision(**params)


def test_ailab_first_while_it_can_start_the_job(queues, tmp_path):
    remote, local, _ = queues
    _ailab_job(remote, tmp_path, 'running')
    decision = _decide(remote, local)
    assert decision['backend'] == 'ailab' and decision['reason'] == 'ailab can start it now'


def test_full_ailab_overflows_a_portable_cpu_job(queues, tmp_path):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    decision = _decide(remote, local)
    assert decision['backend'] == 'local'
    assert decision['ailab']['running_cpus'] == 8


def test_withdrawn_and_terminal_ailab_jobs_do_not_count(queues, tmp_path):
    remote, local, _ = queues
    job = _ailab_job(remote, tmp_path, 'running')
    _ailab_job(remote, tmp_path, 'succeeded')
    withdrawn = _ailab_job(remote, tmp_path, 'queued')
    (remote / 'jobs' / withdrawn / 'WITHDRAWN.by-submitter').write_text('dup\n')
    assert job
    assert _decide(remote, local)['backend'] == 'ailab'


@pytest.mark.parametrize('kwargs, reason', [
    (dict(task_type='math'), 'task type math keeps its own rules'),
    (dict(storage='ssd2'), 'explicit ailab storage ssd2'),
    (dict(free_memory_mib=12000), 'container memory headroom too small'),
    (dict(cpu_threads=8, memory_mib=4096), None),
])
def test_rules_that_keep_a_job_on_ailab(queues, tmp_path, kwargs, reason):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    decision = _decide(remote, local, **kwargs)
    if reason is None:  # 8 CPUs fit the local limit exactly
        assert decision['backend'] == 'local'
    else:
        assert decision == {**decision, 'backend': 'ailab', 'reason': reason}


def test_switch_and_local_limits(queues, tmp_path, monkeypatch):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    monkeypatch.setenv('OPENLABS_COMPUTE_OVERFLOW', '0')
    assert _decide(remote, local)['reason'] == 'automatic overflow is switched off'
    monkeypatch.delenv('OPENLABS_COMPUTE_OVERFLOW')
    for index in range(2):
        lc.submit(_source(tmp_path, name=f's{index}'), ['python3', 'run.py'], cpu_threads=4,
                  memory_mib=4096, wall_seconds=60, queue_root=local)
    # Two queued local jobs already hold the 8 local CPUs.
    assert _decide(remote, local)['reason'] == 'local CPUs full (limit 8)'
    monkeypatch.setenv('OPENLABS_LOCAL_MAX_CPUS', '12')
    assert _decide(remote, local)['backend'] == 'local'
    monkeypatch.setenv('OPENLABS_LOCAL_MAX_JOBS', '2')
    assert _decide(remote, local)['reason'] == 'local queue full (2 of 2 jobs)'


@pytest.mark.parametrize('script', [
    'download-direct uv pip install numpy\n',
    'pip install scipy\n',
    'curl -O https://example.org/x\n',
    '/usr/bin/time-does-not-exist -v python3 run.py\n',
    'ENV=/data/ssd1/openlabs-worker/environments/other\n$ENV/bin/python run.py\n',
    'echo $OPENLABS_STORAGE_ROOT\n',
])
def test_jobs_that_would_not_run_unchanged_stay_on_ailab(queues, tmp_path, script):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    decision = _decide(remote, local, texts={'run.sh': script}, argv=['bash', 'run.sh'])
    assert decision['backend'] == 'ailab'
    assert decision['reason'] == 'job is not portable to this container'
    assert decision['not_portable']


def test_registered_environment_alias_is_rewritten_and_recorded(queues, tmp_path):
    remote, local, config = queues
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    alias = '/data/ssd1/openlabs-worker/environments/astro-photometry'
    config.write_text(json.dumps({'environment_aliases': {alias: str(venv)}}))
    script = f'#!/bin/bash\nset -eu\nENV={alias}\nexec "$ENV/bin/python" run.py\n'
    _fill_ailab(remote, tmp_path)
    assert _decide(remote, local, texts={'run.sh': script}, argv=['bash', 'run.sh'])[
        'backend'] == 'local'
    src = _source(tmp_path)
    (src / 'run.sh').write_text(script)
    os.chmod(src / 'run.sh', 0o755)
    job = lc.submit(src, ['bash', 'run.sh'], cpu_threads=4, memory_mib=4096,
                    wall_seconds=60, queue_root=local)
    snapshot = local / 'jobs' / job / 'source' / 'run.sh'
    assert f'ENV={venv}\n' in snapshot.read_text()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o755
    assert alias in (src / 'run.sh').read_text()  # the submitter's file is untouched
    request = json.loads((local / 'jobs' / job / 'request.json').read_text())
    assert [item['file'] for item in request['path_rewrites']] == ['run.sh']


def test_cli_auto_submit_routes_to_local_and_status_wait_follow(queues, tmp_path, capsys):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    before = set(os.listdir(remote / 'jobs'))
    src = _source(tmp_path)
    (src / '.env').write_text('SECRET=1\n')
    code = rc.main(['submit', '--source', str(src), '--cpus', '4', '--memory-mib', '4096',
                    '--timeout-seconds', '60', '--task-type', 'cpu', '--', 'python3', 'run.py'])
    out = capsys.readouterr()
    assert code == rc.EXIT_OK
    assert 'backend: local' in out.out and 'routing: local' in out.err
    job = next(line.split()[1] for line in out.out.splitlines() if line.startswith('job_id:'))
    assert set(os.listdir(remote / 'jobs')) == before  # nothing queued on ailab
    directory = local / 'jobs' / job
    assert not (directory / 'source' / '.env').exists()  # same exclusions as ailab
    request = json.loads((directory / 'request.json').read_text())
    assert request['routing']['backend'] == 'local'
    assert json.loads((directory / 'status.json').read_text())['state'] == 'queued'  # not started

    status = rc.read_status(job)
    assert status['backend'] == 'local' and status['result_dir'] == str(directory / 'result')
    lc._write_status(directory, state='failed', exit_code=3, error='exit code 3')
    assert rc.main(['wait', job, '--timeout-seconds', '1']) == rc.EXIT_JOB_FAILED
    assert str(directory / 'result') in capsys.readouterr().err
    view = remote_wait.job_state(remote, job, local_root=local)
    assert view['backend'] == 'local' and view['state'] == 'failed'


def test_cli_auto_keeps_ailab_when_it_has_room(queues, tmp_path, capsys):
    remote, local, _ = queues
    src = _source(tmp_path)
    code = rc.main(['submit', '--source', str(src), '--cpus', '4', '--memory-mib', '4096',
                    '--timeout-seconds', '60', '--', 'python3', 'run.py'])
    out = capsys.readouterr()
    assert code == rc.EXIT_OK and 'backend: ailab' in out.out
    assert 'routing: ailab (ailab can start it now)' in out.err
    assert not (local / 'jobs').exists()


def test_cli_explicit_ailab_never_overflows(queues, tmp_path, capsys):
    remote, local, _ = queues
    _fill_ailab(remote, tmp_path)
    src = _source(tmp_path)
    assert rc.main(['submit', '--source', str(src), '--cpus', '4', '--memory-mib', '4096',
                    '--timeout-seconds', '60', '--backend', 'ailab', '--',
                    'python3', 'run.py']) == rc.EXIT_OK
    assert 'backend: ailab' in capsys.readouterr().out
    assert not (local / 'jobs').exists()


def test_dispatch_respects_memory_limit(queues, tmp_path):
    _, local, _ = queues
    first = lc.submit(_source(tmp_path, name='a'), ['python3', 'run.py'], cpu_threads=2,
                      memory_mib=12000, wall_seconds=60, queue_root=local)
    lc.submit(_source(tmp_path, name='b'), ['python3', 'run.py'], cpu_threads=2,
              memory_mib=8000, wall_seconds=60, queue_root=local)
    lc._write_status(local / 'jobs' / first, state='running', runner_pid=os.getpid())
    summary = lc.dispatch(local, max_memory_mib=16384)
    assert summary['started'] == [] and summary['running'] == 1 and summary['queued'] == 1
    assert lc.summary(local)['running_memory_mib'] == 12000


def test_adopt_moves_a_queued_ailab_job_under_the_same_id(queues, tmp_path):
    remote, local, _ = queues
    job = _ailab_job(remote, tmp_path, 'queued')
    moved = lc.adopt_remote(job, remote_root=remote, queue_root=local, reason='test')
    assert moved['job_id'] == job
    ailab = remote / 'jobs' / job
    assert not (ailab / 'READY').exists() and (ailab / 'READY.withdrawn').exists()
    assert (ailab / lc.MOVED_MARKER).exists()
    assert (local / 'jobs' / job / 'READY').exists()
    assert (local / 'jobs' / job / 'source' / 'run.py').read_text() == 'print(1)\n'
    request = json.loads((local / 'jobs' / job / 'request.json').read_text())
    assert request['moved_from']['backend'] == 'ailab'
    assert request['payload_sha256'] == json.loads((ailab / 'request.json').read_text())[
        'payload_sha256']
    # Every reader follows the marker to the local copy; the ailab load ignores it.
    assert lc.locate(job, remote, local) == ('local', local / 'jobs' / job)
    assert rc.read_status(job)['backend'] == 'local'
    view = remote_wait.job_state(remote, job, local_root=local)
    assert view['backend'] == 'local' and view['state'] == 'queued'
    assert lc.ailab_load(remote, CAPS)['queued'] == 0
    lc._write_status(local / 'jobs' / job, state='succeeded', exit_code=0)
    assert remote_wait.job_state(remote, job, local_root=local)['state'] == 'succeeded'


def test_adopt_refuses_running_or_non_portable_jobs_and_changes_nothing(queues, tmp_path):
    remote, local, _ = queues
    running = _ailab_job(remote, tmp_path, 'running')
    with pytest.raises(rc.RemoteComputeError, match='not queued'):
        lc.adopt_remote(running, remote_root=remote, queue_root=local)
    src = tmp_path / 'installer'
    src.mkdir()
    (src / 'run.sh').write_text('uv pip install numpy\npython3 run.py\n')
    job = rc.submit(src, ['bash', 'run.sh'], cpu_threads=4, memory_mib=4096,
                    wall_seconds=60, queue_root=remote).job_id
    with pytest.raises(rc.RemoteComputeError, match='not portable'):
        lc.adopt_remote(job, remote_root=remote, queue_root=local)
    assert (remote / 'jobs' / job / 'READY').exists()
    assert not list((remote / 'jobs' / job).glob('WITHDRAWN*'))
    assert not (local / 'jobs' / job).exists()


def test_runner_records_receipt_and_hides_gpu(queues, tmp_path, monkeypatch):
    _, local, _ = queues
    code_root = tmp_path / 'code'
    (code_root / 'bin').mkdir(parents=True)
    guard = code_root / 'bin' / 'openlabs-resource-guard'
    guard.write_text('#!/bin/bash\n[ "$1" = --task-type ] && [ "$2" = cpu ] && [ "$3" = -- ]'
                     ' || exit 99\nshift 3\nexec "$@"\n')
    guard.chmod(0o755)
    monkeypatch.setattr(lc, 'CODE_ROOT', code_root)
    src = _source(tmp_path, script=(
        'import os, pathlib\n'
        'out = pathlib.Path(os.environ["OPENLABS_OUTPUT_DIR"])\n'
        '(out / "gpu.txt").write_text(repr(os.environ.get("CUDA_VISIBLE_DEVICES")))\n'))
    job = lc.submit(src, ['python3', 'run.py'], cpu_threads=1, memory_mib=256,
                    wall_seconds=60, queue_root=local)
    assert lc.run(job, local) == 0
    directory = local / 'jobs' / job
    status = json.loads((directory / 'status.json').read_text())
    assert status['state'] == 'succeeded' and status['exit_code'] == 0
    receipt = json.loads((directory / 'result' / 'receipt.json').read_text())
    assert receipt['backend'] == 'local' and receipt['outputs'][0]['path'] == 'gpu.txt'
    assert (directory / 'result' / 'outputs' / 'gpu.txt').read_text() == "''"
    assert rc.read_status(job)['receipt_sha256'] == status['receipt_sha256']
