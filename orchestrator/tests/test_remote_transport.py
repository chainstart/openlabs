from pathlib import Path
import importlib.util,io,json,sys,tarfile,time
import pytest

TOOLS=Path(__file__).resolve().parents[2]/'tools/remote-compute'
def load(name):
 spec=importlib.util.spec_from_file_location('test_remote_'+name,TOOLS/(name+'.py'))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
@pytest.fixture
def protocol():return load('protocol')
@pytest.fixture
def bridge(protocol,monkeypatch):
 monkeypatch.setitem(sys.modules,'protocol',protocol);return load('bridge')
def request(protocol,payload):
 return {'schema_version':protocol.SCHEMA,'job_id':'a'*32,'backend':'ailab','argv':['python3','main.py'],'resources':{'cpu_threads':8,'memory_mib':49152,'wall_seconds':60},'payload_sha256':protocol.digest(payload),'payload_bytes':payload.stat().st_size,'created_at':'2026-11-11T00:00:00+00:00'}
def archive(tmp_path,name='payload.tar.gz'):
 p=tmp_path/name
 with tarfile.open(p,'w:gz') as t:
  info=tarfile.TarInfo('main.py');info.size=9;t.addfile(info,io.BytesIO(b'print(1)\n'))
 return p

def test_full_dedicated_machine_budget_and_math_label(protocol,tmp_path):
 r=request(protocol,archive(tmp_path));r['task_type']='math';assert protocol.validate(r)==r
 r['resources']['cpu_threads']=9
 with pytest.raises(ValueError):protocol.validate(r)

def test_remote_storage_name_is_validated(protocol,tmp_path):
 r=request(protocol,archive(tmp_path));r['storage']='ssd4';assert protocol.validate(r)==r
 r['storage']='ssd9'
 with pytest.raises(ValueError,match='storage'):protocol.validate(r)

@pytest.mark.parametrize('name,kind',[('../outside','file'),('/outside','file'),('link','symlink'),('hard','hardlink')])
def test_extract_rejects_escaping_and_link_entries(protocol,tmp_path,name,kind):
 p=tmp_path/'unsafe.tar.gz'
 with tarfile.open(p,'w:gz') as t:
  m=tarfile.TarInfo(name)
  if kind=='symlink':m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd'
  if kind=='hardlink':m.type=tarfile.LNKTYPE;m.linkname='outside'
  t.addfile(m)
 with pytest.raises(ValueError):protocol.extract(p,tmp_path/'out')
 assert not (tmp_path/'outside').exists()

def test_stream_receive_checks_hash_and_truncation(protocol,tmp_path):
 with pytest.raises(ValueError,match='checksum'):protocol.receive(io.BytesIO(b'ab'),tmp_path/'bad',2,'0'*64)
 with pytest.raises(ValueError,match='truncated'):protocol.receive(io.BytesIO(b'a'),tmp_path/'short',2,'0'*64)

def test_private_atomic_state(protocol,tmp_path):
 p=tmp_path/'state.json';protocol.atomic(p,{'state':'queued'});assert p.stat().st_mode&0o777==0o600
 assert json.loads(p.read_text())['state']=='queued'

def test_result_transport_binds_receipt_to_submitted_payload(protocol,bridge,tmp_path,monkeypatch):
 job=tmp_path/('a'*32);job.mkdir();payload=archive(job);r=request(protocol,payload);protocol.atomic(job/'request.json',r)
 result=tmp_path/'remote-result';result.mkdir();protocol.atomic(result/'receipt.json',{'job_id':job.name,'state':'succeeded','payload_sha256':r['payload_sha256']});(result/'stdout.log').write_text('done\n')
 pack=tmp_path/'result.tar.gz';protocol.pack(result,pack)
 header={'ok':True,'job_id':job.name,'state':'succeeded','result_sha256':protocol.digest(pack),'result_bytes':pack.stat().st_size}
 class SSH:
  def __init__(self,*a,**kw):self.stdin=io.BytesIO();self.stdout=io.BytesIO(json.dumps(header).encode()+b'\n'+pack.read_bytes())
  def wait(self,timeout=None):return 0
  def poll(self):return 0
 monkeypatch.setattr(bridge.subprocess,'Popen',SSH)
 bridge.process(job,{'ssh_config':'unused'})
 assert (job/'result/stdout.log').read_text()=='done\n'
 status=json.loads((job/'status.json').read_text());assert status['state']=='succeeded'
 assert status['receipt_sha256']==protocol.digest(job/'result/receipt.json')

def test_bad_queue_request_fails_without_ssh(protocol,bridge,tmp_path):
 job=tmp_path/('a'*32);job.mkdir();protocol.atomic(job/'request.json',{'job_id':'a'*32})
 (job/'READY').write_text('ready');bridge.handle_job(job,{'ssh_config':'unused'})
 assert json.loads((job/'status.json').read_text())['state']=='failed'
 assert not (job/'READY').exists()

def test_transport_failure_preserves_job_for_retry(protocol,bridge,tmp_path,monkeypatch):
 job=tmp_path/('a'*32);job.mkdir();payload=archive(job);protocol.atomic(job/'request.json',request(protocol,payload));(job/'READY').write_text('ready')
 def unavailable(*args):raise RuntimeError('temporary network failure')
 monkeypatch.setattr(bridge,'process',unavailable);bridge.handle_job(job,{})
 status=json.loads((job/'status.json').read_text());assert status['state']=='running';assert status['retry_after']>time.time();assert (job/'READY').exists()

def test_prompt_advertises_dedicated_ailab_without_local_math_cap(tmp_path):
 path=TOOLS.parent.parent/'packages/research-core/lab_runner.py';spec=importlib.util.spec_from_file_location('remote_prompt_runner',path);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
 assert runner._remote_compute_notice(tmp_path,'math')==''
 (tmp_path/'config').mkdir();(tmp_path/'config/remote-compute.json').write_text('{"enabled":true}')
 notice=runner._remote_compute_notice(tmp_path,'math')
 assert '--task-type math' in notice and 'all 8 CPUs' in notice
 assert 'does not impose' in notice and 'database writes stay' in notice
 assert '--storage ssd1' in notice and 'OPENLABS_STORAGE_ROOTS' in notice
