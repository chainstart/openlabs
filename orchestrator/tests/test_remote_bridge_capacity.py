"""WSL bridge: submitted ailab jobs keep their capacity and keep being polled.

Regression for 2026-11-20: an SSH timeout made the bridge drop a running job from its
in-memory table, freeing its threads; with the queue full the job was never polled
again while new jobs were admitted on top of it (38 declared threads on 28).
"""
from concurrent.futures import Future
from pathlib import Path
import importlib.util,io,json,sys

import pytest

TOOLS=Path(__file__).resolve().parents[2]/'tools/remote-compute'


def load(name):
    spec=importlib.util.spec_from_file_location('test_bridge_capacity_'+name,TOOLS/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def protocol():
    return load('protocol')


@pytest.fixture
def bridge(protocol,monkeypatch):
    monkeypatch.setitem(sys.modules,'protocol',protocol);return load('bridge')


@pytest.fixture
def gateway(protocol,monkeypatch):
    monkeypatch.setitem(sys.modules,'protocol',protocol)
    monkeypatch.setitem(sys.modules,'storage',load('storage'))
    return load('gateway')


class Clock:
    def __init__(self,t=1_000_000.0):self.t=t
    def __call__(self):return self.t


class Pool:
    """submit() records the session; sync=True runs it at once (a finished session)."""
    def __init__(self,sync=False):self.sync=sync;self.calls=[]
    def submit(self,fn,job,config):
        f=Future();self.calls.append((fn,job.name,f))
        if self.sync:
            fn(job,config);f.set_result(None)
        return f
    def names(self,fn=None):return [name for f,name,_ in self.calls if fn is None or f is fn]


CONFIG={'capacity':{'cpu_threads':28,'memory_mib':62961},'max_concurrent_jobs':28}


def make_job(protocol,queue,index,threads=8,memory=4096,wall=5400,status=None):
    job=queue/'jobs'/(f'{index:x}'*32)[:32];job.mkdir(parents=True)
    (job/'payload.tar.gz').write_bytes(b'payload')
    protocol.atomic(job/'request.json',{'schema_version':protocol.SCHEMA,'job_id':job.name,'backend':'ailab','argv':['python3','main.py'],'resources':{'cpu_threads':threads,'memory_mib':memory,'wall_seconds':wall},'payload_sha256':'0'*64,'payload_bytes':7,'created_at':'2026-11-20T00:00:00+00:00'})
    protocol.atomic(job/'status.json',status or {'job_id':job.name,'state':'queued','updated_at':'x'})
    (job/'READY').write_text(job.name+'\n')
    return job


def status(job):return json.loads((job/'status.json').read_text())


def running(job,clock,**extra):
    return {'job_id':job if isinstance(job,str) else job.name,'state':'running','updated_at':'x','started_epoch':clock()-600,**extra}


def test_ssh_timeout_does_not_release_capacity(protocol,bridge,tmp_path):
    clock=Clock();queue=tmp_path
    def unreachable(job,config):
        protocol.atomic(job/'status.json',running(job,clock))
        raise RuntimeError('ssh: connect to host 192.168.71.121 port 22: Connection timed out')
    handle=lambda job,config:bridge.handle_job(job,config,run=unreachable,clock=clock)
    pool=Pool(sync=True)
    first=make_job(protocol,queue,1)
    d=bridge.Dispatcher(queue,CONFIG,pool.submit,clock=clock,handle=handle)
    d.tick()
    assert status(first)['state']=='running' and status(first)['retry_after']>clock()
    assert (first/'READY').exists() and all(f.done() for f in d.active.values())  # session ended
    later=[make_job(protocol,queue,i) for i in range(2,7)]
    load=d.tick()
    # The timed-out job still holds its 8 threads: only two more 8-thread jobs fit in 28.
    assert load['cpu_threads']==24
    admitted=[j for j in later if status(j)['state']=='running']
    assert len(admitted)==2
    assert sum(json.loads((j/'request.json').read_text())['resources']['cpu_threads'] for j in [first,*admitted])<=28
    clock.t+=10_000  # everyone is due again; still nothing beyond capacity
    pool.calls.clear();d.tick()
    assert sorted(pool.names())==sorted([first.name]+[j.name for j in admitted])


def test_submitted_jobs_are_polled_even_when_capacity_is_full(protocol,bridge,tmp_path):
    clock=Clock();queue=tmp_path;pool=Pool()
    # The observed overcommit: five 8-thread jobs running on 28 threads, one in backoff.
    held=[make_job(protocol,queue,i) for i in range(1,6)]
    for j in held:protocol.atomic(j/'status.json',running(j,clock,retry_after=clock()-1))
    protocol.atomic(held[0]/'status.json',running(held[0],clock,retry_after=clock()+60))
    waiting=make_job(protocol,queue,7,threads=1)
    d=bridge.Dispatcher(queue,CONFIG,pool.submit,clock=clock,handle='poll',cancel='cancel')
    load=d.tick()
    assert load['cpu_threads']==40
    assert sorted(pool.names('poll'))==sorted(j.name for j in held[1:])
    assert waiting.name not in pool.names()
    d.tick()  # sessions still open: no duplicate sessions
    assert len(pool.calls)==4
    clock.t+=61;d.tick()
    assert held[0].name in pool.names('poll') and waiting.name not in pool.names()


def test_restart_rebuilds_occupancy_from_queue(protocol,bridge,tmp_path):
    clock=Clock();queue=tmp_path
    for i in range(1,4):
        j=make_job(protocol,queue,i);protocol.atomic(j/'status.json',running(j,clock))
    big=make_job(protocol,queue,5,threads=8);small=make_job(protocol,queue,6,threads=4)
    done=make_job(protocol,queue,7,status={'job_id':'7'*32,'state':'succeeded','updated_at':'x'})
    pool=Pool()
    d=bridge.Dispatcher(queue,CONFIG,pool.submit,clock=clock,handle='poll')  # fresh process
    load=d.tick()
    assert big.name not in pool.names() and small.name in pool.names()
    assert load=={'cpu_threads':28,'memory_mib':4*4096,'jobs':4}
    assert not (done/'READY').exists()


def test_admitted_job_counts_before_its_session_writes_running(protocol,bridge,tmp_path):
    clock=Clock();queue=tmp_path;pool=Pool()
    jobs=[make_job(protocol,queue,i) for i in range(1,6)]
    d=bridge.Dispatcher(queue,CONFIG,pool.submit,clock=clock,handle='poll')
    d.tick();d.tick();d.tick()
    assert len(pool.calls)==3 and d.tick()['cpu_threads']==24


def test_transport_failures_back_off_and_keep_job_running(protocol,bridge,tmp_path):
    clock=Clock();job=make_job(protocol,tmp_path,1,wall=86400)
    protocol.atomic(job/'status.json',running(job,clock))
    def down(job,config):raise OSError('Connection timed out')
    delays=[]
    for _ in range(7):
        bridge.handle_job(job,{},run=down,clock=clock);s=status(job)
        assert s['state']=='running' and (job/'READY').exists()
        delays.append(s['retry_after']-clock());clock.t=s['retry_after']
    assert delays==[15,30,60,120,240,300,300]
    clock.t+=10_000;bridge.handle_job(job,{},run=down,clock=clock)  # a long-held session
    s=status(job);assert s['state']=='running' and s['transport_failures']==1


def test_wall_time_exceeded_while_unreachable_fails_and_cancels_on_ailab(protocol,bridge,tmp_path):
    clock=Clock();queue=tmp_path
    job=make_job(protocol,queue,1,threads=8,wall=5400)
    protocol.atomic(job/'status.json',{**running(job,clock),'started_epoch':clock()-5400-301})
    def down(job,config):raise RuntimeError('ssh: connect to host 192.168.71.121 port 22: Connection timed out')
    bridge.handle_job(job,{},run=down,clock=clock)
    s=status(job)
    assert s['state']=='failed' and s['remote_cancel']=='pending' and not (job/'READY').exists()
    newcomers=[make_job(protocol,queue,i) for i in (2,3,4)]
    replies=[RuntimeError('still unreachable'),{'ok':True,'job_id':job.name,'unit_state':'inactive'}]
    def cancel(job,config):
        r=replies.pop(0)
        if isinstance(r,Exception):raise r
        return r
    pool=Pool(sync=True)
    d=bridge.Dispatcher(queue,CONFIG,pool.submit,clock=clock,handle=lambda j,c:None,
                        cancel=lambda j,c:bridge.handle_cancel(j,c,run=cancel,clock=clock))
    load=d.tick()
    # Unconfirmed: the job keeps its 8 threads, so only two of three 8-thread jobs start.
    assert load['cpu_threads']==24 and newcomers[2].name not in pool.names()
    s=status(job);assert s['remote_cancel']=='pending' and s['retry_after']==clock()+15
    d.tick();assert pool.names(None).count(job.name)==1  # backoff respected
    clock.t+=15;d.tick()
    s=status(job);assert s['remote_cancel']=='done' and s['state']=='failed'
    d.tick();assert newcomers[2].name in pool.names()


def test_old_gateway_without_cancel_releases_after_refusal(protocol,bridge,tmp_path):
    clock=Clock();job=make_job(protocol,tmp_path,1)
    protocol.atomic(job/'status.json',{**running(job,clock),'state':'failed','remote_cancel':'pending'})
    bridge.handle_cancel(job,{},run=lambda j,c:{'ok':False,'retryable':False,'error':'only probe and run are supported'},clock=clock)
    assert status(job)['remote_cancel']=='unsupported'
    occupying,new=bridge.classify(tmp_path,clock)
    assert occupying==[] and new==[]


def test_value_errors_still_fail_immediately(protocol,bridge,tmp_path):
    clock=Clock();job=make_job(protocol,tmp_path,1)
    def refused(job,config):raise ValueError('receipt does not bind the submitted job')
    bridge.handle_job(job,{},run=refused,clock=clock)
    s=status(job);assert s['state']=='failed' and 'remote_cancel' not in s and not (job/'READY').exists()


def test_ssh_sessions_detect_dead_connections(bridge):
    command=bridge.ssh_command({'ssh_config':'cfg'})
    assert 'ServerAliveInterval=30' in command and command[-1]=='openlabs-ailab'


def run_gateway(gateway,monkeypatch,header,states):
    calls=[]
    def fake_run(cmd,**kw):
        calls.append(cmd)
        class R:
            stdout=states.pop(0)+'\n' if cmd[2]=='is-active' else ''
            returncode=0
        return R()
    monkeypatch.setattr(gateway.subprocess,'run',fake_run)
    out=io.BytesIO()
    monkeypatch.setattr(gateway.sys,'stdin',type('S',(),{'buffer':io.BytesIO((json.dumps(header)+'\n').encode())})())
    monkeypatch.setattr(gateway.sys,'stdout',type('S',(),{'buffer':out})())
    gateway.main()
    return calls,json.loads(out.getvalue())


def test_gateway_cancel_stops_the_job_unit(gateway,monkeypatch):
    calls,reply=run_gateway(gateway,monkeypatch,{'op':'cancel','job_id':'b'*32},['inactive'])
    assert calls[0]==['systemctl','--user','stop','openlabs-job-'+'b'*32+'.service']
    assert reply=={'ok':True,'retryable':False,'job_id':'b'*32,'unit_state':'inactive'}
    calls,reply=run_gateway(gateway,monkeypatch,{'op':'cancel','job_id':'b'*32},['deactivating'])
    assert reply['ok'] is False and reply['retryable'] is True


def test_gateway_cancel_rejects_bad_identity(gateway,monkeypatch):
    with pytest.raises(ValueError):
        run_gateway(gateway,monkeypatch,{'op':'cancel','job_id':'../x'},[])
