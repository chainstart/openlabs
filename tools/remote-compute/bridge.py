#!/usr/bin/env python3
"""WSL-owned dispatcher. Only the configured ailab SSH endpoint is reachable.

Each job's SSH session to the gateway is idempotent: the gateway launches the job's
systemd unit once (started.json) and every later session for the same job only
waits for and returns its receipt. So "polling" a job means opening another session.

Jobs in the queue fall into two classes, re-derived from the queue directory on every
pass (so a restarted bridge rebuilds the same picture):

* submitted: status "running" with READY present. The job may already be executing on
  ailab. It always counts against capacity and is always polled (with backoff after a
  transport failure) until it is succeeded or failed, whether or not capacity is full.
* new: READY present, not yet running. Only these are subject to the capacity check.

A submitted job that passes started + wall + grace while ailab cannot be reached is
failed (unchanged rule) and an ailab-side stop of its unit is queued
(``remote_cancel: pending``); the job keeps its capacity until the stop is confirmed.
"""
import argparse,datetime,fcntl,json,os,re,shutil,subprocess,sys,time,traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from protocol import validate,receive,extract,digest,atomic

GRACE_SECONDS=300
RETRY_BASE_SECONDS=15
RETRY_MAX_SECONDS=300
TRANSPORT_ERRORS=(OSError,subprocess.SubprocessError,RuntimeError,ValueError)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def ssh_command(config):
 # ServerAlive: a silently dead connection errors out in about two minutes instead of
 # blocking the session (and its job's polling) forever.
 return ['ssh','-F',config['ssh_config'],'-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=30','-o','ServerAliveCountMax=4','openlabs-ailab']

def read_json(path):
 try:return json.loads(Path(path).read_text()) if Path(path).exists() else {}
 except (OSError,ValueError):return {}

def backoff(failures):
 return min(RETRY_BASE_SECONDS*2**max(failures-1,0),RETRY_MAX_SECONDS)

def process(job,config):
 request=validate(json.loads((job/'request.json').read_text()))
 if request['job_id']!=job.name:raise ValueError('queue job directory mismatch')
 payload=job/'payload.tar.gz'
 if payload.is_symlink() or payload.stat().st_size!=request['payload_bytes'] or digest(payload)!=request['payload_sha256']:raise ValueError('queued payload checksum mismatch')
 statuspath=job/'status.json'
 previous=read_json(statuspath)
 started=previous.get('started_epoch',time.time())
 status={'job_id':job.name,'state':'running','updated_at':now(),'started_epoch':started}
 for key in ['transport_failures','last_failure_epoch']:
  if key in previous:status[key]=previous[key]
 atomic(statuspath,status)
 errorlog=job/'transport.log'
 with errorlog.open('ab') as err:
  child=subprocess.Popen(ssh_command(config),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err)
  try:
   child.stdin.write((json.dumps({'op':'run','request':request})+'\n').encode());child.stdin.flush()
   with payload.open('rb') as src:shutil.copyfileobj(src,child.stdin,1024*1024)
   child.stdin.close()
   line=child.stdout.readline(131073)
   if not line or len(line)>131072:raise RuntimeError('SSH endpoint returned no valid response')
   response=json.loads(line)
   if not response.get('ok'):
    if response.get('retryable'):raise RuntimeError(response.get('error','remote temporarily unavailable'))
    raise ValueError(response.get('error','remote refused request'))
   if response.get('job_id')!=job.name or response.get('state') not in ['succeeded','failed']:raise ValueError('response identity/state mismatch')
   size=response.get('result_bytes');checksum=response.get('result_sha256','')
   if type(size) is not int or not 0<size<=2*1024**3 or not re.fullmatch('[0-9a-f]{64}',checksum):raise ValueError('invalid result size/checksum')
   part=job/'result.tar.gz.part';receive(child.stdout,part,size,checksum)
   if child.wait(timeout=30)!=0:raise RuntimeError('SSH transport failed after result transfer')
   pending=job/'result.new'
   if pending.exists():shutil.rmtree(pending)
   extract(part,pending)
   receipt=json.loads((pending/'receipt.json').read_text())
   if receipt.get('job_id')!=job.name or receipt.get('payload_sha256')!=request['payload_sha256'] or receipt.get('state')!=response['state']:raise ValueError('receipt does not bind the submitted job')
   if (job/'result').exists():raise ValueError('result already exists; refusing overwrite')
   pending.rename(job/'result');part.rename(job/'result.tar.gz')
   atomic(statuspath,{'job_id':job.name,'state':receipt['state'],'updated_at':now(),'receipt_sha256':digest(job/'result/receipt.json'),'result_sha256':checksum,'backend':'ailab'})
   (job/'READY').unlink(missing_ok=True)
  finally:
   if child.poll() is None:child.terminate()
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:child.kill();child.wait()

def cancel_remote(job,config):
 """Ask the gateway to stop the job's ailab unit; returns the gateway's JSON reply."""
 with (job/'transport.log').open('ab') as err:
  child=subprocess.Popen(ssh_command(config),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err)
  try:
   child.stdin.write((json.dumps({'op':'cancel','job_id':job.name})+'\n').encode());child.stdin.close()
   line=child.stdout.readline(131073)
   if not line or len(line)>131072:raise RuntimeError('SSH endpoint returned no valid response')
   return json.loads(line)
  finally:
   if child.poll() is None:child.terminate()
   try:child.wait(timeout=5)
   except subprocess.TimeoutExpired:child.kill();child.wait()

def eligible(queue):
 for job in sorted((queue/'jobs').iterdir()):
  if not job.is_dir() or job.is_symlink() or not re.fullmatch('[0-9a-f]{32}',job.name) or not (job/'READY').is_file():continue
  s=read_json(job/'status.json')
  if s.get('state') in ['succeeded','failed']:(job/'READY').unlink(missing_ok=True);continue
  if time.time()<s.get('retry_after',0):continue
  yield job

def handle_job(job,config,run=None,clock=time.time):
 p=job/'status.json'
 try:(run or process)(job,config)
 except TRANSPORT_ERRORS as exc:
  old=read_json(p)
  started=old.get('started_epoch',clock())
  try:wall=json.loads((job/'request.json').read_text())['resources']['wall_seconds']
  except (OSError,KeyError,ValueError,TypeError):wall=0
  timed_out=clock()>started+wall+GRACE_SECONDS
  failed=isinstance(exc,ValueError) or timed_out
  # A failure long after the previous one (e.g. a session that held for hours) starts
  # the backoff afresh.
  recent=clock()-old.get('last_failure_epoch',0)<=2*RETRY_MAX_SECONDS
  failures=(int(old.get('transport_failures',0)) if recent else 0)+1
  status={'job_id':job.name,'state':'failed' if failed else 'running','updated_at':now(),'started_epoch':started,'retry_after':clock()+backoff(failures),'transport_failures':failures,'last_failure_epoch':clock(),'error':str(exc)}
  if failed and timed_out and not isinstance(exc,ValueError):
   # The job may still be alive on ailab (its unit also has RuntimeMaxSec); make sure
   # it is stopped there, now or once ailab is reachable again.
   status.update(error='wall time + grace exceeded without a receipt (ailab unreachable): '+str(exc),remote_cancel='pending',retry_after=clock())
  atomic(p,status)
  if failed:(job/'READY').unlink(missing_ok=True)

def handle_cancel(job,config,run=None,clock=time.time):
 p=job/'status.json'
 try:response=(run or cancel_remote)(job,config)
 except TRANSPORT_ERRORS as exc:
  old=read_json(p);failures=int(old.get('cancel_failures',0))+1
  atomic(p,{**old,'updated_at':now(),'cancel_failures':failures,'retry_after':clock()+backoff(failures),'cancel_error':str(exc)})
  return
 old=read_json(p)
 if response.get('ok'):
  atomic(p,{**old,'updated_at':now(),'remote_cancel':'done','remote_cancel_at':now(),'remote_unit_state':response.get('unit_state')})
 elif response.get('retryable'):
  failures=int(old.get('cancel_failures',0))+1
  atomic(p,{**old,'updated_at':now(),'cancel_failures':failures,'retry_after':clock()+backoff(failures),'cancel_error':response.get('error') or 'unit still active: '+str(response.get('unit_state'))})
 else:
  # An older gateway without the cancel operation: the unit's RuntimeMaxSec still ends
  # it on ailab, so stop holding capacity for it.
  atomic(p,{**old,'updated_at':now(),'remote_cancel':'unsupported','cancel_error':response.get('error','remote refused cancel')})

def resources_of(job):
 try:return validate(json.loads((job/'request.json').read_text()))['resources']
 except (OSError,ValueError,KeyError,TypeError,AttributeError):return None

def classify(queue,clock=time.time):
 """Scan the queue: (occupying, new). occupying = [(job, kind, resources, due)]
 for submitted jobs ('poll') and failed jobs whose ailab stop is pending ('cancel');
 new = READY jobs not yet submitted and due for dispatch."""
 occupying=[];new=[]
 for job in sorted((queue/'jobs').iterdir()):
  if not job.is_dir() or job.is_symlink() or not re.fullmatch('[0-9a-f]{32}',job.name):continue
  s=read_json(job/'status.json');state=s.get('state');due=clock()>=s.get('retry_after',0)
  if state=='failed' and s.get('remote_cancel')=='pending':
   occupying.append((job,'cancel',resources_of(job),due));(job/'READY').unlink(missing_ok=True);continue
  if not (job/'READY').is_file():continue
  if state in ['succeeded','failed']:(job/'READY').unlink(missing_ok=True);continue
  if state=='running':occupying.append((job,'poll',resources_of(job),due))
  elif due:new.append(job)
 return occupying,new

class Dispatcher:
 def __init__(self,queue,config,submit,clock=time.time,handle=handle_job,cancel=handle_cancel):
  self.queue=queue;self.config=config;self.submit=submit;self.clock=clock;self.handle=handle;self.cancel=cancel
  self.capacity=config.get('capacity',{'cpu_threads':8,'memory_mib':62961})
  self.max_jobs=config.get('max_concurrent_jobs',8)
  self.active={}  # job name -> future of its current SSH session

 def tick(self):
  for name,future in list(self.active.items()):
   if future.done():
    del self.active[name]
    try:future.result()
    except Exception:traceback.print_exc(file=sys.stderr)
  occupying,new=classify(self.queue,self.clock)
  cpu=memory=0;tracked=set(self.active)
  for job,kind,resources,due in occupying:
   tracked.add(job.name)
   if resources:cpu+=resources['cpu_threads'];memory+=resources['memory_mib']
   if job.name in self.active or not due:continue
   self.active[job.name]=self.submit(self.handle if kind=='poll' else self.cancel,job,self.config)
  for job in new:
   if job.name in tracked:
    # Admitted on an earlier pass, its session has not yet written "running".
    resources=resources_of(job)
    if resources and job.name in self.active:cpu+=resources['cpu_threads'];memory+=resources['memory_mib']
    continue
   resources=resources_of(job)
   if resources is None:self.handle(job,self.config);continue
   if len(tracked)>=self.max_jobs:break
   if cpu+resources['cpu_threads']>self.capacity['cpu_threads'] or memory+resources['memory_mib']>self.capacity['memory_mib']:continue
   self.active[job.name]=self.submit(self.handle,job,self.config);tracked.add(job.name)
   cpu+=resources['cpu_threads'];memory+=resources['memory_mib']
  return {'cpu_threads':cpu,'memory_mib':memory,'jobs':len(tracked)}

def step(queue,config):
 for job in eligible(queue):handle_job(job,config);return True
 return False

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
 config=json.loads(Path(args.config).read_text());queue=Path(config['queue']);(queue/'jobs').mkdir(parents=True,exist_ok=True,mode=0o700)
 with (queue/'bridge.lock').open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if args.once:step(queue,config);return
  # Submitted jobs are polled even beyond capacity (e.g. after an earlier overcommit),
  # so the session pool is sized well above the admission limit.
  workers=config.get('max_transport_sessions',max(64,2*config.get('max_concurrent_jobs',8)))
  with ThreadPoolExecutor(max_workers=workers) as pool:
   dispatcher=Dispatcher(queue,config,pool.submit)
   while True:
    dispatcher.tick()
    time.sleep(1)
if __name__=='__main__':main()
