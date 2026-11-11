#!/usr/bin/env python3
"""Forced SSH command: fixed JSON+archive compute protocol, no shell interface."""
import sys,os,json,subprocess,time,fcntl,shutil,datetime
from pathlib import Path
from protocol import validate,receive,extract,pack,digest,atomic
from storage import inventory,locate_job
INSTALL=Path('/usr/local/lib/openlabs-remote')

def respond(data,archive=None):
 sys.stdout.buffer.write((json.dumps(data)+'\n').encode());sys.stdout.buffer.flush()
 if archive:
  with open(archive,'rb') as f:shutil.copyfileobj(f,sys.stdout.buffer,1024*1024)
  sys.stdout.buffer.flush()

def main():
 os.umask(0o077)
 line=sys.stdin.buffer.readline(131073)
 if not line or len(line)>131072:raise ValueError('invalid protocol header')
 header=json.loads(line);op=header.get('op')
 if op=='probe':
  limits=subprocess.check_output(['systemctl','--user','show','openlabs-compute.slice','-p','CPUQuotaPerSecUSec','-p','MemoryHigh','-p','MemoryMax','-p','MemorySwapMax','-p','TasksMax'],text=True)
  respond({'ok':True,'backend':'ailab','limits':limits,'storage':inventory(),'tools':{x:bool(shutil.which(x)) for x in ['python3','uv','gcc','g++','cmake','ninja','podman','bwrap','git']}});return
 if op!='run':raise ValueError('only probe and run are supported')
 r=validate(header.get('request',{}));job,volume=locate_job(r['job_id'],r.get('storage','auto'));job.mkdir(mode=0o700,parents=True,exist_ok=True)
 with (job/'gateway.lock').open('a+') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:respond({'ok':False,'retryable':True,'error':'job is already active'});return
  incoming=job/'incoming.part';receive(sys.stdin.buffer,incoming,r['payload_bytes'],r['payload_sha256'])
  requestpath=job/'request.json'
  if requestpath.exists():
   old=json.loads(requestpath.read_text())
   if old!=r:raise ValueError('job identity reused with different request')
   incoming.unlink()
  else:
   incoming.rename(job/'payload.tar.gz');extract(job/'payload.tar.gz',job/'payload');atomic(requestpath,r)
  result=job/'result';result.mkdir(mode=0o700,exist_ok=True);unit='openlabs-job-'+r['job_id']+'.service'
  if not (result/'receipt.json').exists():
   started=job/'started.json'
   if not started.exists():
    resources=r['resources'];slice_name='openlabs-compute-math.slice' if r.get('task_type')=='math' else 'openlabs-compute.slice';atomic(started,{'started_at':time.time(),'unit':unit})
    cmd=['systemd-run','--user','--quiet','--service-type=exec','--unit='+unit,'--slice='+slice_name,'--property=KillMode=control-group','--property=OOMPolicy=stop','--property=CPUQuota='+str(resources['cpu_threads']*100)+'%','--property=MemoryMax='+str(resources['memory_mib'])+'M','--property=MemoryHigh=infinity','--property=MemorySwapMax=infinity','--property=TasksMax=infinity','--property=RuntimeMaxSec='+str(resources['wall_seconds']+10),'--property=StandardOutput=append:'+str(job/'supervisor.log'),'--property=StandardError=append:'+str(job/'supervisor.log'),'--setenv=HOME=/home/openlabs-worker','--setenv=PATH=/home/openlabs-worker/.local/bin:/usr/local/bin:/usr/bin:/bin','--','/usr/bin/python3',str(INSTALL/'runner.py'),str(job)]
    launched=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    if launched.returncode:
     atomic(result/'receipt.json',{'schema_version':'openlabs.remote-receipt.v1','job_id':r['job_id'],'backend':'ailab','state':'failed','error':'systemd launch failed: '+launched.stderr[-2000:],'exit_code':125,'payload_sha256':r['payload_sha256']})
   deadline=json.loads(started.read_text())['started_at']+r['resources']['wall_seconds']+45
   while not (result/'receipt.json').exists():
    active=subprocess.run(['systemctl','--user','is-active',unit],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True).stdout.strip()
    if active not in ['active','activating','deactivating'] or time.time()>deadline:
     atomic(result/'receipt.json',{'schema_version':'openlabs.remote-receipt.v1','job_id':r['job_id'],'backend':'ailab','state':'failed','error':'worker stopped without a completion receipt: '+active,'exit_code':125,'payload_sha256':r['payload_sha256']});break
    time.sleep(1)
  archive=job/'result.tar.gz'
  if not archive.exists():pack(result,archive)
  receipt=json.loads((result/'receipt.json').read_text())
  respond({'ok':True,'job_id':r['job_id'],'state':receipt['state'],'result_sha256':digest(archive),'result_bytes':archive.stat().st_size},archive)
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,subprocess.SubprocessError) as exc:
  respond({'ok':False,'retryable':False,'error':str(exc)});sys.exit(1)
