#!/usr/bin/env python3
"""WSL-owned dispatcher. Only the configured ailab SSH endpoint is reachable."""
import argparse,datetime,fcntl,json,os,re,shutil,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from protocol import validate,receive,extract,digest,atomic

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def process(job,config):
 request=validate(json.loads((job/'request.json').read_text()))
 if request['job_id']!=job.name:raise ValueError('queue job directory mismatch')
 payload=job/'payload.tar.gz'
 if payload.is_symlink() or payload.stat().st_size!=request['payload_bytes'] or digest(payload)!=request['payload_sha256']:raise ValueError('queued payload checksum mismatch')
 statuspath=job/'status.json'
 previous=json.loads(statuspath.read_text()) if statuspath.exists() else {}
 started=previous.get('started_epoch',time.time())
 atomic(statuspath,{'job_id':job.name,'state':'running','updated_at':now(),'started_epoch':started})
 command=['ssh','-F',config['ssh_config'],'-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=10','openlabs-ailab']
 errorlog=job/'transport.log'
 with errorlog.open('ab') as err:
  child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err)
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

def eligible(queue):
 for job in sorted((queue/'jobs').iterdir()):
  if not job.is_dir() or job.is_symlink() or not re.fullmatch('[0-9a-f]{32}',job.name) or not (job/'READY').is_file():continue
  p=job/'status.json'
  try:s=json.loads(p.read_text()) if p.exists() else {}
  except (OSError,ValueError):s={}
  if s.get('state') in ['succeeded','failed']:(job/'READY').unlink(missing_ok=True);continue
  if time.time()<s.get('retry_after',0):continue
  yield job

def handle_job(job,config):
 p=job/'status.json'
 try:process(job,config)
 except (OSError,subprocess.SubprocessError,RuntimeError,ValueError) as exc:
  try:old=json.loads(p.read_text()) if p.exists() else {}
  except (OSError,ValueError):old={}
  started=old.get('started_epoch',time.time())
  try:wall=json.loads((job/'request.json').read_text())['resources']['wall_seconds']
  except (OSError,KeyError,ValueError,TypeError):wall=0
  failed=isinstance(exc,ValueError) or time.time()>started+wall+300
  atomic(p,{'job_id':job.name,'state':'failed' if failed else 'running','updated_at':now(),'started_epoch':started,'retry_after':time.time()+15,'error':str(exc)})
  if failed:(job/'READY').unlink(missing_ok=True)

def step(queue,config):
 for job in eligible(queue):handle_job(job,config);return True
 return False

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
 config=json.loads(Path(args.config).read_text());queue=Path(config['queue']);(queue/'jobs').mkdir(parents=True,exist_ok=True,mode=0o700)
 with (queue/'bridge.lock').open('a+') as f:
  fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if args.once:step(queue,config);return
  capacity=config.get('capacity',{'cpu_threads':8,'memory_mib':62961});running={}
  with ThreadPoolExecutor(max_workers=config.get('max_concurrent_jobs',8)) as pool:
   while True:
    for identity,(future,resources) in list(running.items()):
     if future.done():future.result();del running[identity]
    cpu=sum(r['cpu_threads'] for _,r in running.values());memory=sum(r['memory_mib'] for _,r in running.values())
    for job in eligible(queue):
     if job.name in running:continue
     try:resources=validate(json.loads((job/'request.json').read_text()))['resources']
     except (OSError,ValueError,KeyError,TypeError):handle_job(job,config);continue
     if len(running)>=config.get('max_concurrent_jobs',8):break
     if cpu+resources['cpu_threads']>capacity['cpu_threads'] or memory+resources['memory_mib']>capacity['memory_mib']:continue
     running[job.name]=(pool.submit(handle_job,job,config),resources);cpu+=resources['cpu_threads'];memory+=resources['memory_mib']
    time.sleep(1)
if __name__=='__main__':main()
