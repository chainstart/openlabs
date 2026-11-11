import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path

import pytest

from openlabs import remote_compute as rc


def make_source(root: Path) -> Path:
    src = root / 'src'
    (src / 'pkg').mkdir(parents=True)
    (src / 'pkg' / 'model.py').write_text('print("hi")\n')
    run = src / 'run.sh'
    run.write_text('#!/bin/sh\necho ok\n')
    run.chmod(0o755)
    (src / 'data.csv').write_text('a,b\n1,2\n')
    return src


@pytest.fixture
def queue(tmp_path):
    return tmp_path / 'queue'


def submit(src, queue, **kwargs):
    params = dict(cpu_threads=2, memory_mib=1024, wall_seconds=60, queue_root=queue)
    params.update(kwargs)
    return rc.submit(src, ['python3', 'pkg/model.py'], **params)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_submit_writes_archive_request_hash_status_and_ready(tmp_path, queue):
    src = make_source(tmp_path)
    result = submit(src, queue)
    job = queue / 'jobs' / result.job_id
    assert result.job_dir == job
    assert len(result.job_id) == 32 and int(result.job_id, 16) >= 0

    request = json.loads((job / 'request.json').read_text())
    assert set(request) == {
        'schema_version', 'job_id', 'backend', 'argv', 'resources',
        'payload_sha256', 'payload_bytes', 'created_at',
    }
    assert request['schema_version'] == 'openlabs.remote-compute.v1'
    assert request['job_id'] == result.job_id
    assert request['backend'] == 'ailab'
    assert request['argv'] == ['python3', 'pkg/model.py']
    assert request['resources'] == {'cpu_threads': 2, 'memory_mib': 1024, 'wall_seconds': 60}
    assert request['created_at'].endswith('+00:00')

    payload = (job / 'payload.tar.gz').read_bytes()
    assert request['payload_sha256'] == hashlib.sha256(payload).hexdigest()
    assert request['payload_bytes'] == len(payload)

    with tarfile.open(job / 'payload.tar.gz') as archive:
        members = {m.name: m for m in archive.getmembers()}
        assert set(members) == {'pkg', 'pkg/model.py', 'run.sh', 'data.csv'}
        for member in members.values():
            assert not member.name.startswith('/') and '..' not in member.name.split('/')
            assert member.mode & 0o7000 == 0
            assert member.uid == 0 and member.gid == 0
        assert members['run.sh'].mode & 0o111
        assert archive.extractfile('data.csv').read() == b'a,b\n1,2\n'

    status = json.loads((job / 'status.json').read_text())
    assert status == {'job_id': result.job_id, 'state': 'queued', 'updated_at': request['created_at']}
    assert (job / 'READY').is_file()

    for directory in (queue, queue / 'jobs', job):
        assert mode(directory) == 0o700
    for name in ('payload.tar.gz', 'request.json', 'status.json', 'READY'):
        assert mode(job / name) == 0o600
    assert not [p for p in job.iterdir() if p.name.startswith('.')]


def test_setuid_bits_are_stripped_but_exec_kept(tmp_path, queue):
    src = make_source(tmp_path)
    tool = src / 'tool'
    tool.write_text('x')
    tool.chmod(0o4755)
    if not mode(tool) & 0o4000:
        pytest.skip('filesystem does not keep setuid bit')
    result = submit(src, queue)
    with tarfile.open(result.job_dir / 'payload.tar.gz') as archive:
        assert archive.getmember('tool').mode == 0o755


def test_credentials_and_tool_dirs_are_excluded(tmp_path, queue):
    src = make_source(tmp_path)
    for directory in ('.git', '.venv', 'venv', '__pycache__', 'node_modules',
                      'secret-key', '.ssh', '.claude', '.codex', 'pkg/__pycache__'):
        (src / directory).mkdir(parents=True, exist_ok=True)
        (src / directory / 'inner.txt').write_text('SECRET-SENTINEL')
    for name in ('.env', '.env.local', 'id_rsa', 'id_ed25519', 'server.pem', 'tls.key', '.netrc'):
        (src / name).write_text('SECRET-SENTINEL')
    (src / 'notes.txt').write_text('-----BEGIN OPENSSH PRIVATE KEY-----\nSECRET-SENTINEL\n')
    (src / 'id_rsa.pub').write_text('ssh-rsa AAAA public')

    result = submit(src, queue)
    with tarfile.open(result.job_dir / 'payload.tar.gz') as archive:
        names = set(archive.getnames())
        for member in archive.getmembers():
            if member.isfile():
                assert b'SECRET-SENTINEL' not in archive.extractfile(member).read()
    assert names == {'pkg', 'pkg/model.py', 'run.sh', 'data.csv', 'id_rsa.pub'}
    assert '.env.local' in result.excluded and 'notes.txt' in result.excluded
    assert '.git/' in result.excluded and 'pkg/__pycache__/' in result.excluded


@pytest.mark.parametrize('kind', ['file', 'dir', 'dangling', 'nested'])
def test_symlinks_are_rejected_and_leave_no_job(tmp_path, queue, kind):
    src = make_source(tmp_path)
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside')
    if kind == 'file':
        (src / 'link').symlink_to(outside)
    elif kind == 'dir':
        (src / 'link').symlink_to(tmp_path)
    elif kind == 'dangling':
        (src / 'link').symlink_to(tmp_path / 'missing')
    else:
        (src / 'pkg' / 'link').symlink_to('../data.csv')
    with pytest.raises(rc.RemoteComputeError, match='symlink'):
        submit(src, queue)
    assert not (queue / 'jobs').exists() or not list((queue / 'jobs').iterdir())


def test_symlinked_source_root_is_rejected(tmp_path, queue):
    src = make_source(tmp_path)
    alias = tmp_path / 'alias'
    alias.symlink_to(src)
    with pytest.raises(rc.RemoteComputeError, match='symlink'):
        submit(alias, queue)


def test_special_files_are_rejected(tmp_path, queue):
    src = make_source(tmp_path)
    os.mkfifo(src / 'pipe')
    with pytest.raises(rc.RemoteComputeError, match='special file'):
        submit(src, queue)


@pytest.mark.parametrize('name', ['/etc/passwd', '../x', 'a/../b', './a', 'a//b', '', 'a\\b'])
def test_traversal_and_absolute_arcnames_are_rejected(name):
    with pytest.raises(rc.RemoteComputeError):
        rc.safe_arcname(name)


def test_relative_arcnames_are_accepted():
    assert rc.safe_arcname('a/b.c') == 'a/b.c'
    assert rc.safe_arcname('..hidden') == '..hidden'


@pytest.mark.parametrize('kwargs', [
    dict(cpu_threads=0), dict(cpu_threads=9), dict(cpu_threads=True), dict(cpu_threads=2.0),
    dict(memory_mib=127), dict(memory_mib=62962),
    dict(wall_seconds=0), dict(wall_seconds=31536001),
    dict(backend='other'),
])
def test_resource_and_backend_limits_are_enforced(tmp_path, queue, kwargs):
    src = make_source(tmp_path)
    with pytest.raises(rc.RemoteComputeError):
        submit(src, queue, **kwargs)
    assert not queue.exists()


def test_resource_bounds_are_inclusive(tmp_path, queue):
    src = make_source(tmp_path)
    submit(src, queue, cpu_threads=1, memory_mib=128, wall_seconds=1)
    submit(src, queue, cpu_threads=8, memory_mib=62961, wall_seconds=31536000)


@pytest.mark.parametrize('argv', [[], [''], ['echo', ''], ['a\x00b'], 'echo hi', [1]])
def test_invalid_argv_is_rejected(tmp_path, queue, argv):
    src = make_source(tmp_path)
    with pytest.raises(rc.RemoteComputeError):
        rc.submit(src, argv, cpu_threads=1, memory_mib=128, wall_seconds=1, queue_root=queue)


def test_shell_command_is_kept_as_argv(tmp_path, queue):
    src = make_source(tmp_path)
    result = rc.submit(src, ['bash', '-c', 'echo $HOME && ls'], cpu_threads=1,
                       memory_mib=128, wall_seconds=1, queue_root=queue)
    assert result.request['argv'] == ['bash', '-c', 'echo $HOME && ls']


def test_size_and_file_count_limits(tmp_path, queue):
    src = make_source(tmp_path)
    with pytest.raises(rc.RemoteComputeError, match='more than 2 files'):
        submit(src, queue, max_files=2)
    with pytest.raises(rc.RemoteComputeError, match='exceeds 10 bytes'):
        submit(src, queue, max_bytes=10)
    assert rc.MAX_PAYLOAD_SOURCE_BYTES == 1024 ** 3 and rc.MAX_PAYLOAD_FILES == 10000


def test_missing_or_file_source_is_rejected(tmp_path, queue):
    with pytest.raises(rc.RemoteComputeError, match='does not exist'):
        submit(tmp_path / 'missing', queue)
    (tmp_path / 'f').write_text('x')
    with pytest.raises(rc.RemoteComputeError, match='not a directory'):
        submit(tmp_path / 'f', queue)


def test_default_queue_root_prefers_env_and_ignores_cwd(tmp_path, monkeypatch):
    assert rc.default_queue_root({'OPENLABS_REMOTE_QUEUE': str(tmp_path / 'q')}) == tmp_path / 'q'
    with pytest.raises(rc.RemoteComputeError):
        rc.default_queue_root({'OPENLABS_REMOTE_QUEUE': 'relative/q'})
    monkeypatch.chdir(tmp_path)
    default = rc.default_queue_root({'HOME': '/home/someone'})
    assert default.is_absolute()
    if Path('/.dockerenv').exists():
        assert default == Path('/workspace/.openlabs-remote')
    else:
        assert default == Path('/home/someone/work/projects/.openlabs-remote')


def write_status(queue, job_id, **fields):
    job = queue / 'jobs' / job_id
    job.mkdir(parents=True, exist_ok=True)
    (job / 'status.json').write_text(json.dumps({'job_id': job_id, 'updated_at': 'x', **fields}))


JOB = 'a' * 32


def test_read_status_validates_fields(tmp_path, queue):
    write_status(queue, JOB, state='running')
    assert rc.read_status(JOB, queue)['state'] == 'running'
    write_status(queue, JOB, state='exploded')
    with pytest.raises(rc.RemoteComputeError, match='unknown state'):
        rc.read_status(JOB, queue)
    write_status(queue, JOB, state='succeeded', receipt_sha256='nothex')
    with pytest.raises(rc.RemoteComputeError, match='receipt_sha256'):
        rc.read_status(JOB, queue)
    with pytest.raises(rc.RemoteComputeError, match='no status'):
        rc.read_status('b' * 32, queue)
    for bad in ('../' + 'a' * 29, 'A' * 32, 'a' * 31):
        with pytest.raises(rc.RemoteComputeError, match='job id'):
            rc.read_status(bad, queue)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_times_out_while_running(queue):
    write_status(queue, JOB, state='running')
    fake = FakeClock()
    outcome = rc.wait_for(JOB, timeout_seconds=5, queue_root=queue, clock=fake.clock, sleep=fake.sleep)
    assert outcome.timed_out and outcome.status['state'] == 'running'
    assert fake.sleeps == [2.0, 2.0, 1.0]


def test_wait_returns_terminal_state(queue):
    write_status(queue, JOB, state='queued')
    fake = FakeClock()

    def sleep(seconds):
        fake.sleep(seconds)
        if len(fake.sleeps) == 2:
            write_status(queue, JOB, state='succeeded', receipt_sha256='f' * 64)

    outcome = rc.wait_for(JOB, timeout_seconds=60, queue_root=queue, clock=fake.clock, sleep=sleep)
    assert not outcome.timed_out
    assert outcome.status == {'job_id': JOB, 'updated_at': 'x', 'state': 'succeeded', 'receipt_sha256': 'f' * 64}


def test_cli_submit_status_and_wait_exit_codes(tmp_path, queue, monkeypatch, capsys):
    monkeypatch.setenv('OPENLABS_REMOTE_QUEUE', str(queue))
    monkeypatch.chdir(tmp_path)
    src = make_source(tmp_path)
    (src / '.env').write_text('TOKEN=SECRET-SENTINEL')
    code = rc.main(['submit', '--source', str(src), '--cpus', '2', '--memory-mib', '512',
                    '--timeout-seconds', '30', '--', 'python3', '-c', 'print(1)'])
    out, err = capsys.readouterr()
    assert code == 0
    assert 'SECRET-SENTINEL' not in out + err
    job_id = out.split('job_id: ')[1].split()[0]
    job = queue / 'jobs' / job_id
    assert f'job_dir: {job}' in out
    assert json.loads((job / 'request.json').read_text())['argv'] == ['python3', '-c', 'print(1)']

    assert rc.main(['status', job_id]) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'queued'

    monkeypatch.setattr(rc.time, 'sleep', lambda s: None)
    assert rc.main(['wait', job_id, '--timeout-seconds', '0']) == rc.EXIT_TIMEOUT
    capsys.readouterr()

    (job / 'result').mkdir()
    (job / 'result' / 'stderr.log').write_text('boom')
    (job / 'status.json').write_text(json.dumps({
        'job_id': job_id, 'state': 'failed', 'updated_at': 'y', 'error': 'exit 1'}))
    assert rc.main(['wait', job_id]) == rc.EXIT_JOB_FAILED
    assert (job / 'result' / 'stderr.log').read_text() == 'boom'
    assert (job / 'payload.tar.gz').exists()
    capsys.readouterr()

    (job / 'status.json').write_text(json.dumps({
        'job_id': job_id, 'state': 'succeeded', 'updated_at': 'z', 'receipt_sha256': '0' * 64}))
    assert rc.main(['wait', job_id]) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'succeeded'


def test_cli_rejects_missing_separator_and_bad_resources(tmp_path, queue, monkeypatch, capsys):
    monkeypatch.setenv('OPENLABS_REMOTE_QUEUE', str(queue))
    src = make_source(tmp_path)
    assert rc.main(['submit', '--source', str(src), '--cpus', '1', '--memory-mib', '128',
                    '--timeout-seconds', '1', 'echo']) == rc.EXIT_INVALID
    assert rc.main(['submit', '--source', str(src), '--cpus', '9', '--memory-mib', '128',
                    '--timeout-seconds', '1', '--', 'echo']) == rc.EXIT_INVALID
    assert rc.main(['submit', '--source', str(src), '--cpus', '1', '--memory-mib', '128',
                    '--timeout-seconds', '1', '--']) == rc.EXIT_INVALID
    assert rc.main(['status', 'f' * 32]) == rc.EXIT_STATUS_ERROR
    assert not (queue / 'jobs').exists() or not list((queue / 'jobs').iterdir())


def test_ailab_math_can_use_full_host_instead_of_old_18_gib_cap(tmp_path, queue):
    result = submit(make_source(tmp_path), queue, cpu_threads=8, memory_mib=49152,
                    task_type='math')
    assert result.request['task_type'] == 'math'
    assert result.request['resources']['memory_mib'] == 49152


def test_invalid_task_type_is_rejected_before_publication(tmp_path, queue):
    with pytest.raises(rc.RemoteComputeError, match='task_type'):
        submit(make_source(tmp_path), queue, task_type='unknown')
    assert not queue.exists()


def test_explicit_ssd_is_bound_to_request(tmp_path, queue):
    result = submit(make_source(tmp_path), queue, storage='ssd4')
    assert result.request['storage'] == 'ssd4'


def test_unknown_ssd_is_rejected_before_publication(tmp_path, queue):
    with pytest.raises(rc.RemoteComputeError, match='storage'):
        submit(make_source(tmp_path), queue, storage='ssd9')
    assert not queue.exists()
